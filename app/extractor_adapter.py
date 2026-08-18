from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata

from sqlalchemy.orm import Session

from .models import MasterProduct, Offer, OfferPriceReference, Store
from .prospect_models import OfferProvenance, ProspectArchive
from .admin_learning import resolve_product_alias
from .category_classifier import ensure_auto_category
from .engine_v140.collectors import CollectedOffer
from .engine_v140.offer_quality import evaluate_offer
from .engine_v140.product_cleaning import clean_product_name
from .engine_v140.services import classify_offer


@dataclass(frozen=True)
class ImportSummary:
    received: int = 0
    imported: int = 0
    created_products: int = 0
    created_offers: int = 0
    updated_offers: int = 0
    rejected_online: int = 0
    rejected_quality: int = 0
    rejected_store: int = 0
    rejected_date: int = 0


_LIDL_EXPLICIT_ONLINE_ONLY_PATTERNS = (
    r'"(?:onlineOnly|online_only|isOnlineOnly|webOnly|shopOnly)"\s*:\s*true',
    r'"(?:channel|salesChannel|availability|offerType|badge|label)"\s*:\s*"[^"]*(?:online only|nur online|online-only|onlineshop)[^"]*"',
    r'\bnur\s+online\b',
    r'\bonline\s*only\b',
    r'\bnur\s+im\s+online-?shop\b',
    r'\bshoppe\s+auf\s+lidl\.de\b',
)


def _row_has_explicit_online_only_marker(row: CollectedOffer) -> bool:
    """Return True only for explicit retailer-provided online-only signals.

    Lidl uses canonical ``/p/.../p123`` product URLs for both normal leaflet
    offers and web-shop-only items. Therefore a Lidl product URL by itself must
    never be treated as evidence that an offer is online-only.
    """
    text = row.source_text or ""
    return any(re.search(pattern, text, flags=re.I) for pattern in _LIDL_EXPLICIT_ONLINE_ONLY_PATTERNS)


def _row_is_local_offer(row: CollectedOffer) -> bool:
    if (row.retailer or "").strip().lower() == "lidl":
        return not _row_has_explicit_online_only_marker(row)
    return bool(row.local_store_offer)


def _ascii_fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_master_key(name: str, quantity: float | None = None, unit: str | None = None) -> str:
    text = clean_product_name(name).lower()
    text = _ascii_fold(text)
    text = re.sub(r"\b(?:versch\.?|verschiedene)\s+sorten\b", " ", text)
    text = re.sub(r"\b(?:ursprung|herkunft)\s*:\s*[^,;]+", " ", text)
    text = re.sub(r"\b(?:kl\.?|klasse|handelsklasse)\s*[ivx]+\b", " ", text)
    text = re.sub(r"^(?:deutschland|niederlande|spanien|italien|frankreich|portugal|griechenland|osterreich)\s*[-–:]\s*", "", text)
    text = re.sub(r"[^a-z0-9äöüß+]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if quantity is not None and unit:
        q = float(quantity)
        q_text = str(int(q)) if q.is_integer() else (f"{q:.3f}".rstrip("0").rstrip("."))
        u = unit.lower().replace("liter", "l").replace("stück", "st")
        text = f"{text}|{q_text}{u}"
    return text[:320]


def package_size_label(quantity: float | None, unit: str | None) -> str | None:
    if quantity is None or not unit:
        return None
    q = float(quantity)
    shown = str(int(q)) if q.is_integer() else str(q).replace(".", ",")
    return f"{shown} {unit}"


def _date(value: str | None):
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _find_store(db: Session, row: CollectedOffer) -> Store | None:
    store = db.query(Store).filter(Store.name == row.store_name).first()
    if store:
        return store
    return db.query(Store).filter(Store.retailer == row.retailer, Store.name.ilike(f"%{row.store_name}%")).first()


def _prospect_page(source_text: str | None) -> int | None:
    match = re.search(r"\bPDF\s+Seite\s+(\d+)\b", source_text or "", re.I)
    if not match:
        return None
    page = int(match.group(1))
    return page if page > 0 else None


def _matching_archive(db: Session, store: Store, valid_from, valid_to, source_url: str | None) -> ProspectArchive | None:
    query = db.query(ProspectArchive).filter(ProspectArchive.store_id == store.id)
    if valid_from:
        query = query.filter(ProspectArchive.valid_from == valid_from)
    if valid_to:
        query = query.filter(ProspectArchive.valid_to == valid_to)
    candidates = query.order_by(ProspectArchive.fetched_at.desc()).all()
    if not candidates:
        return None
    if source_url:
        exact = [x for x in candidates if x.source_url == source_url or x.pdf_url == source_url]
        if exact:
            return exact[0]
    return candidates[0]


def _save_offer_provenance(db: Session, *, offer: Offer, store: Store, row: CollectedOffer, valid_from, valid_to) -> None:
    page = _prospect_page(row.source_text)
    if page is None:
        return
    archive = _matching_archive(db, store, valid_from, valid_to, row.source_url or None)
    if archive is None or page > archive.page_count:
        return
    existing = db.query(OfferProvenance).filter(
        OfferProvenance.offer_id == offer.id,
        OfferProvenance.prospect_archive_id == archive.id,
        OfferProvenance.prospect_page == page,
    ).first()
    if existing:
        existing.source_text = row.source_text or existing.source_text
        existing.source_url = row.source_url or existing.source_url
        existing.collected_at = datetime.utcnow()
        return
    db.add(OfferProvenance(
        offer_id=offer.id,
        prospect_archive_id=archive.id,
        prospect_page=page,
        source_text=row.source_text or None,
        source_url=row.source_url or None,
        collected_at=datetime.utcnow(),
    ))


def _save_price_reference(db: Session, offer: Offer, row: CollectedOffer) -> None:
    try:
        reference = float(row.regular_price) if row.regular_price is not None else None
    except (TypeError, ValueError):
        reference = None
    if reference is None or reference <= float(offer.price):
        existing = db.query(OfferPriceReference).filter(OfferPriceReference.offer_id == offer.id).first()
        if existing:
            db.delete(existing)
        return
    raw = (row.source_text or "").lower()
    reference_type = "uvp" if any(token in raw for token in ('"uvp"', 'recommendedretailprice', '"rrp"')) else "regular"
    discount = round((1.0 - float(offer.price) / reference) * 100.0, 1)
    existing = db.query(OfferPriceReference).filter(OfferPriceReference.offer_id == offer.id).first()
    if existing:
        existing.reference_price = reference
        existing.reference_type = reference_type
        existing.discount_percent = discount
    else:
        db.add(OfferPriceReference(
            offer_id=offer.id,
            reference_price=reference,
            reference_type=reference_type,
            discount_percent=discount,
        ))


def import_collected_offers(db: Session, rows: list[CollectedOffer]) -> ImportSummary:
    counts = {"received": len(rows), "imported": 0, "created_products": 0, "created_offers": 0, "updated_offers": 0, "rejected_online": 0, "rejected_quality": 0, "rejected_store": 0, "rejected_date": 0}
    for row in rows:
        local, _reason = classify_offer(row.source_text, row.source_url)
        if not _row_is_local_offer(row) or not local:
            counts["rejected_online"] += 1
            continue
        quality = evaluate_offer(row)
        if not quality.accepted:
            counts["rejected_quality"] += 1
            continue
        store = _find_store(db, row)
        if not store or store.retailer != row.retailer:
            counts["rejected_store"] += 1
            continue
        valid_from = _date(row.valid_from)
        valid_to = _date(row.valid_to)
        if not valid_from or not valid_to or valid_to < valid_from:
            counts["rejected_date"] += 1
            continue

        name = clean_product_name(row.product_name)
        key = normalize_master_key(name, row.quantity, row.unit)
        product = resolve_product_alias(db, key)
        if not product:
            product = db.query(MasterProduct).filter(MasterProduct.normalized_key == key).first()
        if not product:
            product = MasterProduct(brand=None, name=name, package_size=package_size_label(row.quantity, row.unit), normalized_key=key)
            db.add(product)
            db.flush()
            counts["created_products"] += 1
        ensure_auto_category(db, product)

        offer = db.query(Offer).filter(
            Offer.store_id == store.id,
            Offer.master_product_id == product.id,
            Offer.valid_from == valid_from,
            Offer.price == float(row.price),
        ).first()
        if not offer:
            offer = Offer(
                store_id=store.id,
                master_product_id=product.id,
                price=float(row.price),
                unit_price=row.unit_price,
                unit_price_unit=row.unit_price_unit,
                valid_from=valid_from,
                valid_to=valid_to,
                local_store_offer=True,
                source_url=row.source_url or None,
            )
            db.add(offer)
            db.flush()
            counts["created_offers"] += 1
        else:
            offer.valid_to = valid_to
            offer.unit_price = row.unit_price
            offer.unit_price_unit = row.unit_price_unit
            offer.local_store_offer = True
            if row.source_url:
                offer.source_url = row.source_url
            counts["updated_offers"] += 1

        _save_price_reference(db, offer, row)
        _save_offer_provenance(db, offer=offer, store=store, row=row, valid_from=valid_from, valid_to=valid_to)
        counts["imported"] += 1

    db.commit()
    return ImportSummary(**counts)
