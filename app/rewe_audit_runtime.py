from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from .clock import app_today
from .config import settings
from .models import Store
from .prospect_models import ProspectArchive


def _parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _validity_from_result(result):
    offers = result.get("offers") or []
    starts = [_parse_date(getattr(row, "valid_from", None)) for row in offers]
    ends = [_parse_date(getattr(row, "valid_to", None)) for row in offers]
    starts = [x for x in starts if x]
    ends = [x for x in ends if x]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _has_archived_prospect(db, store: Store) -> bool:
    """Return whether an immutable archive exists for this store.

    A mutable current prospect pointer may exist even when archive creation
    failed. The audit UI and provenance depend on ProspectArchive, so only that
    table is authoritative for deciding whether the successful-session fallback
    can be skipped.
    """
    return (
        db.query(ProspectArchive.id)
        .filter(ProspectArchive.store_id == store.id)
        .first()
        is not None
    )


def _clean_snapshot_dom(page) -> None:
    """Remove scripts and residual consent overlays from already captured HTML."""
    page.evaluate(
        """() => {
          document.querySelectorAll('script').forEach(el => el.remove());
          const words = ['cookie','cookies','datenschutz','privacy','consent','zustimmen','ablehnen','verarbeitung ihrer daten'];
          const candidates = new Set();
          for (const sel of ['[role="dialog"]','[aria-modal="true"]','[class*="cookie" i]','[id*="cookie" i]','[class*="consent" i]','[id*="consent" i]']) {
            try { document.querySelectorAll(sel).forEach(el => candidates.add(el)); } catch (_) {}
          }
          for (const el of candidates) {
            const text=(el.innerText||el.textContent||'').toLowerCase();
            if (words.some(w => text.includes(w))) el.remove();
          }
          document.documentElement.style.overflow='auto';
          if (document.body) document.body.style.overflow='auto';
        }"""
    )


def archive_rewe_from_collector_result(db, store: Store, result) -> str:
    """Render the HTML that the successful REWE collector already received.

    No second navigation to rewe.de is performed. This avoids the WAF failure
    seen when audit archival ran as a separate browser request after scraping.
    """
    raw = result.get("raw")
    if not raw:
        raise RuntimeError("Erfolgreicher REWE-Lauf enthält kein archivierungsfähiges HTML")
    html = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    if "<html" not in html.lower() and "<body" not in html.lower():
        raise RuntimeError("REWE-Lauf enthält kein HTML-Dokument")

    source_url = result.get("final_url") or getattr(result.get("source"), "url", None) or store.source_url
    if not source_url:
        raise RuntimeError("REWE-Quelle fehlt im erfolgreichen Lauf")

    target_dir = settings.data_dir / "prospects" / "viewer" / str(store.id) / "current"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"rewe-session-web-{store.id}-{app_today().isoformat()}.pdf"

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        context = browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1440, "height": 1100},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36",
        )
        page = context.new_page()
        try:
            page.set_content(html, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                page.wait_for_timeout(1200)
            _clean_snapshot_dom(page)
            page.evaluate("window.scrollTo(0,0)")
            payload = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "8mm", "right": "8mm", "bottom": "8mm", "left": "8mm"},
            )
        finally:
            context.close()
            browser.close()

    if not payload.startswith(b"%PDF"):
        raise RuntimeError("REWE Session-Abbild konnte nicht als PDF erzeugt werden")
    target.write_bytes(payload)

    valid_from, valid_to = _validity_from_result(result)
    from .prospects import save_prospect, _link_web_snapshot_provenance

    row = save_prospect(
        db,
        store,
        period_key="current",
        source_url=source_url,
        pdf_url=f"web-snapshot://captured-session/{store.id}/{app_today().isoformat()}",
        pdf_path=target,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    archive = (
        db.query(ProspectArchive)
        .filter(ProspectArchive.store_id == store.id)
        .order_by(ProspectArchive.fetched_at.desc(), ProspectArchive.id.desc())
        .first()
    )
    linked = 0
    if archive:
        try:
            linked = int(_link_web_snapshot_provenance(db, store, archive) or 0)
        except Exception:
            db.rollback()
    return f"audit=session-web-snapshot:{row.page_count} Seiten; provenance={linked}"


def install() -> None:
    from . import web_collector

    original = web_collector.collect_store_from_web
    if getattr(original, "_lpc_rewe_session_patch", False):
        return

    def wrapped(db, store_name: str):
        result, summary, run = original(db, store_name)
        store = db.query(Store).filter(Store.name == store_name).first()
        if store and store.retailer == "REWE" and getattr(summary, "imported", 0):
            try:
                # The immutable archive table is authoritative. A mutable
                # current pointer may survive a failed WAF archive attempt and
                # must not suppress this successful-session fallback.
                if not _has_archived_prospect(db, store):
                    status = archive_rewe_from_collector_result(db, store, result)
                    web_collector._append_run_diagnostic(db, run, status)
            except Exception as exc:
                db.rollback()
                web_collector._append_run_diagnostic(
                    db,
                    run,
                    f"audit_session_fehler={type(exc).__name__}: {exc}",
                )
        return result, summary, run

    wrapped._lpc_rewe_session_patch = True
    web_collector.collect_store_from_web = wrapped
