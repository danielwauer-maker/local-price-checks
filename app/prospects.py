from __future__ import annotations

from datetime import timedelta, datetime
from html import escape
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .engine_v140.source_registry import source_for_store
from .models import Offer, Store
from .prospect_models import Prospect
from .web_collector import discover_official_pdf, download_pdf, netto_weekly_prospect_url


_REWE_CHALLENGE_MARKERS = (
    "zeig uns, dass du ein mensch bist",
    "waf challenge",
    "bot protection",
    "access denied",
)


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


def _pdf_contains_rewe_challenge(path: str | Path) -> bool:
    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:3]).lower()
        return any(marker in text for marker in _REWE_CHALLENGE_MARKERS)
    except Exception:
        return False


def _render_rewe_offer_catalog_pdf(db: Session, store: Store, source_url: str, target_dir: Path) -> Path:
    """Render a LocalPrices catalog from already imported official REWE offers.

    We intentionally do not try to circumvent REWE's WAF/bot challenge. If REWE
    does not expose a direct PDF, the viewer instead uses the offers that our
    normal collector has already imported from the official market source.
    """
    from playwright.sync_api import sync_playwright

    valid_from, valid_to = _period_dates("current")
    offers = (
        db.query(Offer)
        .filter(
            Offer.store_id == store.id,
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= valid_to,
            Offer.valid_to >= valid_from,
        )
        .order_by(Offer.product.has(), Offer.price.asc())
        .all()
    )
    if not offers:
        raise RuntimeError("Keine aktuellen REWE-Angebote im lokalen Datenbestand verfügbar")

    cards = []
    for offer in offers:
        product = offer.product
        name = escape(product.name if product else "Artikel")
        brand = escape(product.brand or "") if product else ""
        pack = escape(product.package_size or "") if product else ""
        meta = " · ".join(x for x in (brand, pack) if x)
        unit = ""
        if offer.unit_price is not None and offer.unit_price_unit:
            unit = f'<div class="unit">{offer.unit_price:.2f} € / {escape(offer.unit_price_unit)}</div>'
        cards.append(
            f'<article class="offer"><div class="name">{name}</div>'
            f'<div class="meta">{meta}</div><div class="price">{offer.price:.2f} €</div>{unit}</article>'
        )

    html = f"""
    <!doctype html><html lang="de"><head><meta charset="utf-8"><style>
      @page {{ size: A4; margin: 10mm; }}
      * {{ box-sizing: border-box; }}
      body {{ margin:0; font-family: Arial, Helvetica, sans-serif; color:#17231c; background:#fff; }}
      header {{ padding:4mm 2mm 6mm; border-bottom:2px solid #087b4f; margin-bottom:6mm; }}
      .eyebrow {{ color:#087b4f; font-size:10pt; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
      h1 {{ margin:2mm 0 1mm; font-size:24pt; }}
      .sub {{ color:#607066; font-size:10pt; }}
      .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:4mm; }}
      .offer {{ break-inside:avoid; border:1px solid #dce5dd; border-radius:4mm; padding:4mm; min-height:28mm; position:relative; }}
      .name {{ font-size:12pt; font-weight:700; padding-right:28mm; }}
      .meta,.unit {{ color:#66756d; font-size:8.5pt; margin-top:1.5mm; }}
      .price {{ position:absolute; right:4mm; top:4mm; color:#d83b2d; font-size:16pt; font-weight:800; }}
      footer {{ margin-top:6mm; color:#78857d; font-size:7.5pt; }}
    </style></head><body>
      <header><div class="eyebrow">LocalPrices · REWE Angebotskatalog</div>
      <h1>{escape(store.name)}</h1>
      <div class="sub">{escape(store.address)}, {escape(store.postal_code)} {escape(store.city)} · gültig {valid_from.strftime('%d.%m.%Y')}–{valid_to.strftime('%d.%m.%Y')}</div></header>
      <main class="grid">{''.join(cards)}</main>
      <footer>Zusammenstellung aus den für diesen Markt bereits über die offizielle REWE-Quelle importierten Angeboten. Originalquelle: {escape(source_url)}</footer>
    </body></html>
    """

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "rewe-angebotskatalog.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1600}, locale="de-DE")
        page.set_content(html, wait_until="load")
        page.pdf(path=str(target), format="A4", print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        browser.close()
    return target


def discover_and_store_prospect(db: Session, store: Store, period_key: str = "current") -> Prospect | None:
    source_url = prospect_source_url(store, period_key)
    if not source_url:
        return None
    target_dir = settings.data_dir / "prospects" / "viewer" / str(store.id) / period_key

    if store.retailer == "REWE" and period_key == "current":
        pdf_path = _render_rewe_offer_catalog_pdf(db, store, source_url, target_dir)
        return save_prospect(db, store, period_key=period_key, source_url=source_url, pdf_url=source_url, pdf_path=pdf_path)

    pdf_url = discover_official_pdf(source_url)
    pdf_path = download_pdf(pdf_url, target_dir)
    return save_prospect(db, store, period_key=period_key, source_url=source_url, pdf_url=pdf_url, pdf_path=pdf_path)


def current_prospect(db: Session, store: Store, period_key: str) -> Prospect | None:
    row = db.query(Prospect).filter(Prospect.store_id == store.id, Prospect.period_key == period_key, Prospect.active.is_(True)).first()
    if row and store.retailer == "REWE" and row.local_path and _pdf_contains_rewe_challenge(row.local_path):
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
