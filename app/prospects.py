from __future__ import annotations

from datetime import timedelta, datetime
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .engine_v140.source_registry import source_for_store
from .models import Store
from .prospect_models import Prospect
from .web_collector import discover_official_pdf, download_pdf, netto_weekly_prospect_url


def _period_dates(period_key: str):
    today = app_today()
    monday = today - timedelta(days=today.weekday())
    if period_key == "next":
        monday += timedelta(days=7)
    return monday, monday + timedelta(days=6)


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


def save_prospect(db: Session, store: Store, *, period_key: str, source_url: str, pdf_url: str, pdf_path: Path) -> Prospect:
    valid_from, valid_to = _period_dates(period_key)
    try:
        page_count = len(PdfReader(str(pdf_path)).pages)
    except Exception:
        page_count = 0
    row = db.query(Prospect).filter(Prospect.store_id == store.id, Prospect.period_key == period_key).first()
    if not row:
        row = Prospect(store_id=store.id, period_key=period_key, source_url=source_url, pdf_url=pdf_url, local_path=str(pdf_path), page_count=page_count)
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


def _render_rewe_digital_pdf(source_url: str, target_dir: Path) -> Path:
    """Create a local viewer PDF from REWE's official digital offer page.

    REWE no longer publishes a classic paper/PDF prospect for all markets. Its
    official offer page contains the digital prospect/offer presentation. We
    render that official page with Chromium and keep the resulting PDF locally,
    so the app can show it without cross-origin iframe restrictions.
    """
    from playwright.sync_api import sync_playwright

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "rewe-digitalprospekt.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1600}, locale="de-DE")
        page.goto(source_url, wait_until="domcontentloaded", timeout=settings.collector_timeout_seconds * 1000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        # Remove common sticky/header/consent UI from the printout where possible.
        page.evaluate(
            """
            () => {
              const selectors = [
                'header', 'nav', '[role="banner"]', '[data-testid*="cookie"]',
                '[class*="cookie"]', '[class*="Cookie"]', '[class*="sticky"]'
              ];
              for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                  if (el instanceof HTMLElement) el.style.display = 'none';
                }
              }
            }
            """
        )
        page.emulate_media(media="screen")
        page.pdf(
            path=str(target),
            format="A4",
            print_background=True,
            margin={"top": "8mm", "right": "7mm", "bottom": "8mm", "left": "7mm"},
        )
        browser.close()
    return target


def discover_and_store_prospect(db: Session, store: Store, period_key: str = "current") -> Prospect | None:
    source_url = prospect_source_url(store, period_key)
    if not source_url:
        return None
    target_dir = settings.data_dir / "prospects" / "viewer" / str(store.id) / period_key

    # REWE's official public experience is a digital prospect rather than a
    # dependable direct PDF. Render the official market offer page locally.
    if store.retailer == "REWE" and period_key == "current":
        pdf_path = _render_rewe_digital_pdf(source_url, target_dir)
        return save_prospect(
            db,
            store,
            period_key=period_key,
            source_url=source_url,
            pdf_url=source_url,
            pdf_path=pdf_path,
        )

    pdf_url = discover_official_pdf(source_url)
    pdf_path = download_pdf(pdf_url, target_dir)
    return save_prospect(db, store, period_key=period_key, source_url=source_url, pdf_url=pdf_url, pdf_path=pdf_path)


def current_prospect(db: Session, store: Store, period_key: str) -> Prospect | None:
    return db.query(Prospect).filter(Prospect.store_id == store.id, Prospect.period_key == period_key, Prospect.active.is_(True)).first()


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
