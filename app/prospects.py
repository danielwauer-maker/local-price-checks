from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import hashlib
import re

from pypdf import PdfReader
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .engine_v140.source_registry import source_for_store
from .models import Store
from .prospect_models import Prospect, ProspectArchive
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


def _is_invalid_rewe_pdf(path: str | Path) -> bool:
    target = Path(path)
    if target.name.lower() == "rewe-angebotskatalog.pdf":
        return True
    try:
        text = _pdf_text(path, 3).lower()
    except Exception:
        return True
    return any(marker in text for marker in _REWE_INVALID_MARKERS)


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

    # Preserve every distinct original PDF in the database before rotating the
    # current/next UI pointer. This makes historical price checks reproducible.
    archive_prospect_pdf(
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

    # Only real PDF prospects are accepted. In particular REWE must never fall
    # back to a generated LocalPrices catalog or to a rendered WAF page.
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

    if store.retailer == "REWE" and row.local_path and _is_invalid_rewe_pdf(row.local_path):
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
