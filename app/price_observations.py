from __future__ import annotations

from datetime import datetime
from enum import Enum
import hashlib
import json

from sqlalchemy.orm import Session

from .data_operations_models import PriceObservation, SourceProduct
from .engine_v140.collectors import CollectedOffer
from .models import MasterProduct, Offer, Store
from .promotion_rules import has_multibuy_signal


class PriceType(str, Enum):
    NORMAL = "NORMAL"
    PROMOTION = "PROMOTION"
    ADVERTISED_REFERENCE = "ADVERTISED_REFERENCE"
    LOYALTY = "LOYALTY"
    COUPON = "COUPON"
    MULTIBUY = "MULTIBUY"
    UNKNOWN = "UNKNOWN"


def _hash(parts: list[object]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _external_product_id(row: CollectedOffer) -> str | None:
    for name in ("external_product_id", "lidl_product_id", "product_id", "article_id", "sku", "ean", "gtin"):
        value = getattr(row, name, None)
        if value not in (None, ""):
            return str(value).strip()[:160]
    return None


def ensure_source_product(
    db: Session, *, row: CollectedOffer, store: Store, product: MasterProduct, observed_at: datetime
) -> SourceProduct:
    external_id = _external_product_id(row)
    identity_key = _hash([
        store.retailer, store.id, row.source_key, external_id or product.normalized_key,
    ])
    source_product = db.query(SourceProduct).filter_by(identity_key=identity_key).first()
    if source_product is None:
        source_product = SourceProduct(
            master_product_id=product.id,
            store_id=store.id,
            retailer=store.retailer,
            source_key=str(row.source_key)[:160],
            external_product_id=external_id,
            identity_key=identity_key,
            source_name=(row.product_name or product.name)[:240],
            first_observed_at=observed_at,
            last_observed_at=observed_at,
            match_confidence=max(0.0, min(float(row.confidence or 0.0), 1.0)),
        )
        db.add(source_product)
        db.flush()
    else:
        source_product.last_observed_at = observed_at
        source_product.source_name = (row.product_name or source_product.source_name)[:240]
        source_product.match_confidence = max(0.0, min(float(row.confidence or 0.0), 1.0))
    return source_product


def _promotion_type(row: CollectedOffer) -> PriceType:
    text = (row.source_text or "").casefold()
    if has_multibuy_signal(row.source_text):
        return PriceType.MULTIBUY
    if "coupon" in text or "gutschein" in text:
        return PriceType.COUPON
    return PriceType.PROMOTION


def _insert_observation(
    db: Session,
    *,
    row: CollectedOffer,
    offer: Offer,
    store: Store,
    source_product: SourceProduct,
    price: float,
    price_type: PriceType,
    observed_at: datetime,
    collection_run_id: int | None,
    suffix: str,
) -> bool:
    external_id = _external_product_id(row)
    dedupe_key = _hash([
        observed_at.date().isoformat(), offer.master_product_id, store.id, row.source_key,
        external_id, price_type.value, round(float(price), 4),
        round(float(row.unit_price), 4) if row.unit_price is not None else None,
        row.unit_price_unit, offer.valid_from, offer.valid_to, suffix,
    ])
    if db.query(PriceObservation.id).filter_by(dedupe_key=dedupe_key).first():
        return False
    db.add(PriceObservation(
        master_product_id=offer.master_product_id,
        source_product_id=source_product.id,
        store_id=store.id,
        retailer=store.retailer,
        price=float(price),
        unit_price=float(row.unit_price) if row.unit_price is not None else None,
        unit_price_unit=row.unit_price_unit,
        price_type=price_type.value,
        valid_from=offer.valid_from,
        valid_to=offer.valid_to,
        observed_at=observed_at,
        source=str(row.source_key)[:160],
        external_id=external_id,
        dedupe_key=dedupe_key,
        collection_run_id=collection_run_id,
        confidence=max(0.0, min(float(row.confidence or 0.0), 1.0)),
        source_url=row.source_url or None,
    ))
    return True


def persist_offer_price_observations(
    db: Session,
    *,
    row: CollectedOffer,
    offer: Offer,
    store: Store,
    product: MasterProduct,
    collection_run_id: int | None,
    observed_at: datetime | None = None,
) -> int:
    """Persist only source facts. No offer value is promoted to NORMAL here."""
    observed_at = observed_at or datetime.utcnow()
    source_product = ensure_source_product(
        db, row=row, store=store, product=product, observed_at=observed_at
    )
    created = int(_insert_observation(
        db, row=row, offer=offer, store=store, source_product=source_product,
        price=float(offer.price), price_type=_promotion_type(row), observed_at=observed_at,
        collection_run_id=collection_run_id, suffix="offer",
    ))
    if row.regular_price is not None and float(row.regular_price) > float(offer.price):
        created += int(_insert_observation(
            db, row=row, offer=offer, store=store, source_product=source_product,
            price=float(row.regular_price), price_type=PriceType.ADVERTISED_REFERENCE,
            observed_at=observed_at, collection_run_id=collection_run_id, suffix="reference",
        ))
    if row.app_price is not None and float(row.app_price) > 0:
        created += int(_insert_observation(
            db, row=row, offer=offer, store=store, source_product=source_product,
            price=float(row.app_price), price_type=PriceType.LOYALTY,
            observed_at=observed_at, collection_run_id=collection_run_id, suffix="loyalty",
        ))
    return created
