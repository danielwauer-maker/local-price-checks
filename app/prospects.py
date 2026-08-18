from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
import hashlib
import re
import unicodedata

from pypdf import PdfReader
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .engine_v140.source_registry import source_for_store
from .models import Offer, Store
from .prospect_models import OfferProvenance, Prospect, ProspectArchive
from .web_collector import discover_official_pdf, download_pdf, netto_weekly_prospect_url


_REWE_INVALID_MARKERS = (
    "zeig uns, dass du ein mensch bist",
    "waf challenge",
    "bot protection",
    "access denied",
    "localprices · rewe angebotskatalog",
    "localprices - rewe angebotskatalog",
)


def _period_dates(period_key: str) -> tuple[date, date]:
    today = app_today()
    monday = today - timedelta(days=today.weekday())
    if period_key == "next":
        monday += timedelta(days=7)
    return monday, monday + timedelta(days=6)


def _pdf_text(path: str | Path, max_pages: int = 3) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])


def _infer_validity(path: str | Path, period_key: str) -> tuple[date, date]:
    fallback = _period_dates(period_key)
    try:
        text = _pdf_text(path, 2)
    except Exception:
        return fallback
    match = re.search(r"g[üu]ltig\s+ab\s+(\d{1,2}\.\d{1,2}\.\d{4})", text, re.I)
    if not match:
        return fallback
    try:
        start = datetime.strptime(match.group(1), "%d.%m.%Y").date()
    except ValueError:
        return fallback
    return start, start + timedelta(days=6)


def _netto_url_for_period(store: Store, period_key: str) -> str:
    if period_key == "current":
        return netto_weekly_prospect_url(store)
    target = app_today() + timedelta(days=7)
    week = target.isocalendar().week
    return f"https://wochenprospekt.netto-online.de/hz{week:02d}_kess/?storeid={store.external_id}"


def prospect_source_url(store: Store, period_key: str) -> str | None:
    if store.retailer == "Netto Marken-Discount" and store.external_id:
        return _netto_url_for_period(store, period_key)
    if period_key == "next":
        return None
    source = source_for_store(store.name)
    return source.url if source else store.source_url


def is_manual_prospect(row: Prospect | None) -> bool:
    return bool(row and row.source_url.startswith("admin-upload://"))


def is_web_snapshot(row: Prospect | ProspectArchive | None) -> bool:
    return bool(row and row.pdf_url.startswith("web-snapshot://"))


def _is_invalid_rewe_pdf(path: str | Path) -> bool:
    target = Path(path)
    if target.name.lower() == "rewe-angebotskatalog.pdf":
        return True
    try:
        text = _pdf_text(path, 3).lower()
    except Exception:
        return True
    return any(marker in text for marker in _REWE_INVALID_MARKERS)


def _fold(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _render_official_web_snapshot(store: Store, source_url: str, target_dir: Path) -> Path:
    """Render the official market offer page into an immutable PDF audit artifact.

    REWE no longer guarantees a downloadable PDF. This fallback captures the
    official market-specific digital offer page itself; it is explicitly marked
    as a web snapshot and must never be presented as an original retailer PDF.
    """
    if not settings.collector_browser_enabled:
        raise ValueError("Browser-Collector ist deaktiviert; Web-Prospekt kann nicht archiviert werden")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise ValueError("Playwright ist für Web-Prospekt-Archivierung nicht verfügbar") from exc

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"official-web-{store.retailer.lower().replace(' ', '-')}-{store.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
    timeout = max(10, settings.collector_timeout_seconds) * 1000
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        try:
            page.goto(source_url, wait_until="domcontentloaded", timeout=timeout)
            # Best-effort cookie dismissal; absence is harmless.
            for label in ("Alle akzeptieren", "Akzeptieren", "Zustimmen"):
                try:
                    button = page.get_by_role("button", name=label, exact=False)
                    if button.count():
                        button.first.click(timeout=1500)
                        break
                except Exception:
                    pass
            # Trigger lazy loading of the full offer list before printing.
            last_height = 0
            for _ in range(14):
                height = int(page.evaluate("document.body.scrollHeight"))
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(450)
                if height == last_height:
                    break
                last_height = height
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
            body = page.locator("body").inner_text(timeout=3000)
            folded = _fold(body)
            city_ok = not store.city or _fold(store.city) in folded
            offer_signal = "angebote" in folded and len(re.findall(r"\b\d{1,3}[,.]\d{2}\s*€", body)) >= 5
            blocked = any(marker in folded for marker in (_fold(x) for x in _REWE_INVALID_MARKERS[:4]))
            if blocked or not city_ok or not offer_signal:
                raise ValueError("Offizielle Marktseite konnte nicht als valider Angebots-Snapshot bestätigt werden")
            payload = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "8mm", "right": "8mm", "bottom": "8mm", "left": "8mm"},
            )
            target.write_bytes(payload)
        finally:
            browser.close()
    return target


def archive_prospect_pdf(
    db: Session,
    store: Store,
    *,
    period_key: str,
    source_url: str,
    pdf_url: str,
    pdf_path: Path,
    page_count: int,
    valid_from: date | None,
    valid_to: date | None,
) -> ProspectArchive:
    payload = pdf_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    archive = (
        db.query(ProspectArchive)
        .filter(ProspectArchive.store_id == store.id, ProspectArchive.pdf_sha256 == digest)
        .first()
    )
    if archive:
        return archive

    archive = ProspectArchive(
        store_id=store.id,
        retailer=store.retailer,
        period_key=period_key,
        valid_from=valid_from,
        valid_to=valid_to,
        source_url=source_url,
        pdf_url=pdf_url,
        original_filename=pdf_path.name,
        local_path=str(pdf_path),
        page_count=page_count,
        pdf_sha256=digest,
        pdf_bytes=payload,
        fetched_at=datetime.utcnow(),
    )
    db.add(archive)
    db.flush()
    return archive


def _link_web_snapshot_provenance(db: Session, store: Store, archive: ProspectArchive) -> int:
    """Map structured offers to the printed page where their product name occurs."""
    if not archive.pdf_bytes or not is_web_snapshot(archive):
        return 0
    try:
        reader = PdfReader(BytesIO(archive.pdf_bytes))
        page_texts = [_fold(page.extract_text() or "") for page in reader.pages]
    except Exception:
        return 0
    query = db.query(Offer).filter(Offer.store_id == store.id, Offer.local_store_offer.is_(True))
    if archive.valid_from:
        query = query.filter(Offer.valid_from >= archive.valid_from)
    if archive.valid_to:
        query = query.filter(Offer.valid_from <= archive.valid_to)
    linked = 0
    for offer in query.all():
        needle = _fold(offer.product.name)
        if len(needle) < 5:
            continue
        page_no = next((idx + 1 for idx, text in enumerate(page_texts) if needle in text), None)
        if page_no is None:
            continue
        exists = db.query(OfferProvenance).filter_by(
            offer_id=offer.id,
            prospect_archive_id=archive.id,
            prospect_page=page_no,
        ).first()
        if exists:
            continue
        db.add(OfferProvenance(
            offer_id=offer.id,
            prospect_archive_id=archive.id,
            prospect_page=page_no,
            source_text=f"Offizielle digitale Angebotsseite · archivierte Web-PDF-Seite {page_no}",
            source_url=archive.source_url,
            collected_at=datetime.utcnow(),
        ))
        linked += 1
    if linked:
        db.commit()
    return linked


def save_prospect(
    db: Session,
    store: Store,
    *,
    period_key: str,
    source_url: str,
    pdf_url: str,
    pdf_path: Path,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> Prospect:
    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
    except Exception as exc:
        raise ValueError("Prospekt ist keine lesbare PDF-Datei") from exc
    if page_count < 1:
        raise ValueError("Prospekt enthält keine Seiten")

    inferred_from, inferred_to = _infer_validity(pdf_path, period_key)
    valid_from = valid_from or inferred_from
    valid_to = valid_to or inferred_to

    archive = archive_prospect_pdf(
        db,
        store,
        period_key=period_key,
        source_url=source_url,
        pdf_url=pdf_url,
        pdf_path=pdf_path,
        page_count=page_count,
        valid_from=valid_from,
        valid_to=valid_to,
    )

    row = db.query(Prospect).filter(Prospect.store_id == store.id, Prospect.period_key == period_key).first()
    if not row:
        row = Prospect(
            store_id=store.id,
            period_key=period_key,
            source_url=source_url,
            pdf_url=pdf_url,
            local_path=str(pdf_path),
            page_count=page_count,
        )
        db.add(row)
    row.source_url = source_url
    row.pdf_url = pdf_url
    row.local_path = str(pdf_path)
    row.valid_from = valid_from
    row.valid_to = valid_to
    row.page_count = page_count
    row.active = True
    row.fetched_at = datetime.utcnow()
    db.commit()
    db.refresh(row)

    if is_web_snapshot(archive):
        _link_web_snapshot_provenance(db, store, archive)
    return row


def save_manual_prospect(
    db: Session,
    store: Store,
    *,
    period_key: str,
    filename: str,
    payload: bytes,
) -> Prospect:
    if period_key not in {"current", "next"}:
        raise ValueError("Ungültiger Prospekt-Zeitraum")
    if not payload.startswith(b"%PDF"):
        raise ValueError("Die Datei ist keine PDF-Datei")
    if len(payload) > 60 * 1024 * 1024:
        raise ValueError("Prospekt ist größer als 60 MB")

    safe_name = Path(filename or "prospekt.pdf").name
    if store.retailer == "REWE" and store.external_id:
        ids = re.findall(r"(?<!\d)(\d{6,7})(?!\d)", safe_name)
        if ids and store.external_id not in ids:
            raise ValueError(f"PDF scheint für einen anderen REWE-Markt bestimmt zu sein ({', '.join(ids)})")

    target_dir = settings.data_dir / "prospects" / "viewer" / str(store.id) / period_key
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"manual-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
    target.write_bytes(payload)

    if store.retailer == "REWE" and _is_invalid_rewe_pdf(target):
        target.unlink(missing_ok=True)
        raise ValueError("Die PDF ist kein gültiges originales REWE-Prospekt")

    valid_from, valid_to = _infer_validity(target, period_key)
    source = f"admin-upload://{safe_name}"
    return save_prospect(
        db,
        store,
        period_key=period_key,
        source_url=source,
        pdf_url=source,
        pdf_path=target,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def discover_and_store_prospect(db: Session, store: Store, period_key: str = "current") -> Prospect | None:
    existing = current_prospect(db, store, period_key)
    if existing and is_manual_prospect(existing):
        return existing

    source_url = prospect_source_url(store, period_key)
    if not source_url:
        return None
    target_dir = settings.data_dir / "prospects" / "viewer" / str(store.id) / period_key

    try:
        pdf_url = discover_official_pdf(source_url)
        pdf_path = download_pdf(pdf_url, target_dir)
        if store.retailer == "REWE" and _is_invalid_rewe_pdf(pdf_path):
            pdf_path.unlink(missing_ok=True)
            raise ValueError("REWE-Quelle liefert kein echtes Prospekt-PDF")
        return save_prospect(
            db,
            store,
            period_key=period_key,
            source_url=source_url,
            pdf_url=pdf_url,
            pdf_path=pdf_path,
        )
    except Exception:
        # REWE has moved to a paperless digital prospect and does not guarantee
        # a downloadable PDF. Archive the official market page automatically so
        # manual QA never depends on a user-uploaded file.
        if store.retailer != "REWE" or period_key != "current":
            raise
        pdf_path = _render_official_web_snapshot(store, source_url, target_dir)
        return save_prospect(
            db,
            store,
            period_key=period_key,
            source_url=source_url,
            pdf_url=f"web-snapshot://{source_url}",
            pdf_path=pdf_path,
        )


def current_prospect(db: Session, store: Store, period_key: str) -> Prospect | None:
    row = (
        db.query(Prospect)
        .filter(
            Prospect.store_id == store.id,
            Prospect.period_key == period_key,
            Prospect.active.is_(True),
        )
        .first()
    )
    if not row:
        return None

    if row.valid_to and row.valid_to < app_today():
        row.active = False
        db.commit()
        return None

    if store.retailer == "REWE" and row.local_path and not is_web_snapshot(row) and _is_invalid_rewe_pdf(row.local_path):
        row.active = False
        db.commit()
        return None
    return row


def ensure_store_prospects(db: Session, store: Store) -> tuple[Prospect | None, Prospect | None]:
    current = current_prospect(db, store, "current")
    nxt = current_prospect(db, store, "next")
    if not current:
        try:
            current = discover_and_store_prospect(db, store, "current")
        except Exception:
            current = None
    if not nxt and store.retailer == "Netto Marken-Discount":
        try:
            nxt = discover_and_store_prospect(db, store, "next")
        except Exception:
            nxt = None
    return current, nxt
