from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import html as html_lib
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .clock import app_today
from .collection_service import CollectionError, collect_pdf_for_store, collect_structured_for_store
from .config import settings
from .models import Store
from .engine_v140.lidl_flipbook import capture_lidl_flipbook
from .engine_v140.lidl_live import lidl_store_page_for, resolve_lidl_leaflet
from .engine_v140.source_registry import source_for_store_record

PDF_RE = re.compile(r"\.pdf(?:$|[?#])", re.I)
INLINE_PDF_RE = re.compile(r"[\"']([^\"']+\.pdf(?:\?[^\"']*)?)[\"']", re.I)
PROSPECT_WORDS = ("prospekt", "wochenprospekt", "angebote", "handzettel", "flyer")


def _rank_link(url: str, text: str = "") -> tuple[int, int]:
    hay = f"{url} {text}".lower()
    score = 0
    if PDF_RE.search(url):
        score += 100
    for word in PROSPECT_WORDS:
        if word in hay:
            score += 10
    if "online" in hay and "prospekt" not in hay:
        score -= 5
    return score, -len(url)


def _inline_pdf_links(base_url: str, html: str) -> list[str]:
    decoded = html_lib.unescape(html).replace("\\/", "/")
    seen: set[str] = set()
    links: list[str] = []
    for raw in INLINE_PDF_RE.findall(decoded):
        url = urljoin(base_url, raw)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _links_from_html(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[tuple[int, int], str]] = []
    seen: set[str] = set()
    for url in _inline_pdf_links(base_url, html):
        seen.add(url)
        candidates.append((_rank_link(url, "prospekt pdf"), url))
    for tag in soup.find_all(["a", "iframe", "embed", "object"]):
        raw = tag.get("href") or tag.get("src") or tag.get("data")
        if not raw:
            continue
        url = urljoin(base_url, str(raw))
        if url in seen:
            continue
        seen.add(url)
        text = tag.get_text(" ", strip=True)
        score = _rank_link(url, text)
        if score[0] > 0:
            candidates.append((score, url))
    candidates.sort(reverse=True)
    return [url for _, url in candidates]


def _rendered_links(url: str) -> list[str]:
    if not settings.collector_browser_enabled:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=settings.collector_timeout_seconds * 1000)
            html = page.content()
            browser.close()
        return _links_from_html(url, html)
    except Exception:
        return []


def discover_official_pdf(source_url: str) -> str:
    headers = {"User-Agent": "LocalPriceChecks/0.3 (+market onboarding)"}
    with httpx.Client(follow_redirects=True, timeout=settings.collector_timeout_seconds, headers=headers) as client:
        response = client.get(source_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type or PDF_RE.search(str(response.url)):
            return str(response.url)
        links = _links_from_html(str(response.url), response.text)
        if not links:
            links = _rendered_links(str(response.url))
        for link in links:
            try:
                probe = client.head(link)
                ctype = probe.headers.get("content-type", "").lower()
                if "application/pdf" in ctype or PDF_RE.search(str(probe.url)):
                    return str(probe.url)
            except Exception:
                if PDF_RE.search(link):
                    return link
    raise CollectionError(f"Kein offizieller PDF-Prospekt auffindbar: {source_url}")


def download_pdf(url: str, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    target = target_dir / f"prospect-{digest}.pdf"
    headers = {"User-Agent": "LocalPriceChecks/0.3 (+market onboarding)"}
    with httpx.Client(follow_redirects=True, timeout=settings.collector_timeout_seconds, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise CollectionError(f"Quelle liefert keine PDF-Datei: {url}")
        target.write_bytes(response.content)
    return target


def netto_weekly_prospect_url(store: Store) -> str:
    if store.retailer != "Netto Marken-Discount":
        raise CollectionError(f"Kein Netto-Markt: {store.name}")
    if not store.external_id:
        raise CollectionError(f"Netto storeid fehlt: {store.name}")
    week = app_today().isocalendar().week
    return f"https://wochenprospekt.netto-online.de/hz{week:02d}_kess/?storeid={store.external_id}"


def _archive_downloaded_prospect(
    db: Session,
    store: Store,
    *,
    source_url: str,
    pdf_url: str,
    pdf_path: Path,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> None:
    from .prospects import save_prospect
    save_prospect(
        db,
        store,
        period_key="current",
        source_url=source_url,
        pdf_url=pdf_url,
        pdf_path=pdf_path,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _ensure_audit_artifact(db: Session, store: Store, source_url: str) -> str:
    """Create an audit artifact and always return a visible diagnostic."""
    primary_error: Exception | None = None
    try:
        from .prospects import discover_and_store_prospect
        row = discover_and_store_prospect(db, store, "current")
        if row:
            kind = "web-snapshot" if row.pdf_url.startswith("web-snapshot://") else "original-pdf"
            return f"audit={kind}:{row.page_count} Seiten"
        primary_error = CollectionError("keine automatische Prospektquelle gefunden")
    except Exception as exc:
        primary_error = exc
        db.rollback()

    return f"audit_fehler={type(primary_error).__name__}: {primary_error}"


def _append_run_diagnostic(db: Session, run, text: str) -> None:
    if not text:
        return
    try:
        run.message = f"{run.message} | {text}" if run.message else text
        db.add(run)
        db.commit()
    except Exception:
        db.rollback()


def _collect_netto_from_official_prospect(db: Session, store: Store, source):
    prospect_url = netto_weekly_prospect_url(store)
    pdf_url = discover_official_pdf(prospect_url)
    pdf_path = download_pdf(pdf_url, settings.data_dir / "prospects" / source.key)
    _archive_downloaded_prospect(db, store, source_url=prospect_url, pdf_url=pdf_url, pdf_path=pdf_path)
    return collect_pdf_for_store(db, store.name, pdf_path)


def _collect_lidl_from_official_leaflet(db: Session, store: Store, source):
    """Resolve, capture and import the complete current Lidl action leaflet."""
    store_page = lidl_store_page_for(store.name)
    leaflet = resolve_lidl_leaflet(source.url, app_today(), store_page_url=store_page)
    resolved_source = replace(
        source,
        url=leaflet.url,
        mode="leaflet_viewer",
        locality="store_specific" if leaflet.store_context_confirmed else "regional_chain",
        notes=(
            f"Automatisch aufgelöst: {leaflet.title}; "
            f"Filialkontext={'bestätigt' if leaflet.store_context_confirmed else 'nicht bestätigt'}"
        ),
        store_specific=leaflet.store_context_confirmed,
    )

    capture_holder = {}

    def collector(src):
        capture = capture_lidl_flipbook(
            src,
            valid_from=leaflet.valid_from,
            valid_to=leaflet.valid_to,
            target_dir=settings.data_dir / "prospects" / "viewer" / str(store.id) / "current",
        )
        capture_holder["capture"] = capture
        return {
            "source": src,
            "raw": b"",
            "content_type": "application/pdf+html-audit",
            "fetch_mode": capture.fetch_mode,
            "final_url": capture.final_url,
            "offers": capture.offers,
            "status": "parsed" if capture.offers else "no_safe_offers",
            "capture_diagnostics": capture.diagnostics,
            "audit_pdf_path": str(capture.pdf_path),
            "audit_page_count": capture.page_count,
        }

    def archive_before_import(result):
        capture = capture_holder.get("capture")
        if capture is None:
            raise CollectionError("Lidl-Flipbook wurde nicht erzeugt")

        # Prefer an official retailer PDF if the viewer exposes one. Otherwise
        # the complete multi-page viewer capture is archived and explicitly
        # labelled as a web snapshot. Either way it exists before import so
        # ``PDF Seite N`` provenance can attach to the immutable archive.
        try:
            pdf_url = discover_official_pdf(leaflet.url)
            pdf_path = download_pdf(pdf_url, settings.data_dir / "prospects" / "lidl_puderbach")
            _archive_downloaded_prospect(
                db,
                store,
                source_url=leaflet.url,
                pdf_url=pdf_url,
                pdf_path=pdf_path,
                valid_from=leaflet.valid_from,
                valid_to=leaflet.valid_to,
            )
            from .prospects import current_prospect
            row = current_prospect(db, store, "current")
            result["audit_status"] = f"audit=original-pdf:{row.page_count if row else '?'} Seiten"
        except Exception:
            db.rollback()
            _archive_downloaded_prospect(
                db,
                store,
                source_url=leaflet.url,
                pdf_url=f"web-snapshot://{leaflet.url}",
                pdf_path=capture.pdf_path,
                valid_from=leaflet.valid_from,
                valid_to=leaflet.valid_to,
            )
            from .prospects import current_prospect
            row = current_prospect(db, store, "current")
            result["audit_status"] = f"audit=web-snapshot:{row.page_count if row else capture.page_count} Seiten"

    result, summary, run = collect_structured_for_store(
        db,
        store.name,
        source_override=resolved_source,
        collector_fn=collector,
        before_import_fn=archive_before_import,
    )
    context_status = "lidl_filiale=bestätigt" if leaflet.store_context_confirmed else "lidl_filiale=nicht_bestaetigt"
    _append_run_diagnostic(
        db,
        run,
        (
            f"lidl_prospekt={leaflet.valid_from.isoformat()}..{leaflet.valid_to.isoformat()} | "
            f"{context_status} | {result.get('capture_diagnostics','')} | {result.get('audit_status','audit=?')}"
        ),
    )
    return result, summary, run


def collect_store_from_web(db: Session, store_name: str):
    """Collect an active market for QA or production.

    Collection and release are deliberately separate. benchmark_verified is
    only the user-facing release gate. Active unverified markets may be scraped
    so admins can audit them before release. Every successful collection also
    attempts to archive the matching prospect automatically.
    """
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        raise CollectionError(f"Unbekannter Markt: {store_name}")
    if not store.active:
        raise CollectionError(f"Markt ist inaktiv: {store_name}")
    source = source_for_store_record(store)
    if not source:
        raise CollectionError(f"Keine Quelle registriert oder automatisch ableitbar für: {store.name}")

    if store.retailer == "Netto Marken-Discount":
        return _collect_netto_from_official_prospect(db, store, source)
    if store.retailer == "Lidl":
        return _collect_lidl_from_official_leaflet(db, store, source)

    structured_error = None
    try:
        result, summary, run = collect_structured_for_store(db, store.name)
        if summary.imported:
            # Retailers with an explicit artifact adapter already archived the
            # exact successful collector response. Other retailers retain the
            # discovery fallback until their adapters migrate to this lifecycle.
            if not result.get("_artifact_managed"):
                audit_status = _ensure_audit_artifact(db, store, source.url)
                _append_run_diagnostic(db, run, audit_status)
            return result, summary, run
    except Exception as exc:
        structured_error = exc

    try:
        pdf_url = discover_official_pdf(source.url)
        pdf_path = download_pdf(pdf_url, settings.data_dir / "prospects" / source.key)
        _archive_downloaded_prospect(db, store, source_url=source.url, pdf_url=pdf_url, pdf_path=pdf_path)
        return collect_pdf_for_store(db, store.name, pdf_path)
    except Exception as pdf_error:
        if structured_error:
            raise CollectionError(
                f"Strukturierter Abruf fehlgeschlagen: {structured_error}; PDF-Fallback fehlgeschlagen: {pdf_error}"
            ) from pdf_error
        raise
