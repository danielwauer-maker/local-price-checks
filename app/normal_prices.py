from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from sqlalchemy.orm import Session

from .lokero_models import NormalPriceObservation
from .models import Offer, OfferPriceReference

EXPLICIT_REFERENCE_TYPES = {"regular", "uvp", "rrp", "was_price", "retailer_regular"}


def add_normal_price_observation(
    db: Session,
    *,
    master_product_id: int,
    price: float,
    store_id: int | None = None,
    retailer: str | None = None,
    source: str = "manual",
    confidence: float = 1.0,
    notes: str | None = None,
) -> NormalPriceObservation:
    row = NormalPriceObservation(
        master_product_id=master_product_id,
        store_id=store_id,
        retailer=retailer,
        price=float(price),
        source=source,
        confidence=max(0.0, min(float(confidence), 1.0)),
        is_regular_price=True,
        notes=notes,
        observed_at=datetime.utcnow(),
    )
    db.add(row)
    return row


def reference_price_for_offer(db: Session, offer: Offer) -> dict:
    """Return the best defensible regular/reference price for an offer.

    Priority:
      1. explicit retailer reference attached to the concrete offer;
      2. recent manually/observationally confirmed normal prices at that store;
      3. recent confirmed normal prices for the same retailer.

    The method deliberately never treats a promoted offer price itself as a
    normal price. When no defensible reference exists, status is ``unknown``.
    """
    explicit = (
        db.query(OfferPriceReference)
        .filter(OfferPriceReference.offer_id == offer.id)
        .first()
    )
    if explicit and explicit.reference_price > 0:
        ref = float(explicit.reference_price)
        discount = ((ref - float(offer.price)) / ref * 100.0) if ref > float(offer.price) else 0.0
        return {
            "regularPrice": round(ref, 2),
            "source": explicit.reference_type,
            "estimated": explicit.reference_type not in EXPLICIT_REFERENCE_TYPES,
            "discountPercent": round(max(0.0, discount), 1),
            "isRealDiscount": ref > float(offer.price) + 0.004,
            "status": "confirmed" if explicit.reference_type in EXPLICIT_REFERENCE_TYPES else "estimated",
        }

    cutoff = datetime.utcnow() - timedelta(days=120)
    q = db.query(NormalPriceObservation).filter(
        NormalPriceObservation.master_product_id == offer.master_product_id,
        NormalPriceObservation.is_regular_price.is_(True),
        NormalPriceObservation.observed_at >= cutoff,
    )

    store_rows = q.filter(NormalPriceObservation.store_id == offer.store_id).all()
    source = "store_history"
    rows = store_rows
    if not rows and offer.store is not None:
        rows = q.filter(NormalPriceObservation.retailer == offer.store.retailer).all()
        source = "retailer_history"

    values = [float(row.price) for row in rows if row.price and row.price > 0]
    if not values:
        return {
            "regularPrice": None,
            "source": None,
            "estimated": False,
            "discountPercent": None,
            "isRealDiscount": None,
            "status": "unknown",
        }

    ref = float(median(values))
    discount = ((ref - float(offer.price)) / ref * 100.0) if ref > float(offer.price) else 0.0
    return {
        "regularPrice": round(ref, 2),
        "source": source,
        "estimated": True,
        "discountPercent": round(max(0.0, discount), 1),
        "isRealDiscount": ref > float(offer.price) + 0.004,
        "status": "estimated",
    }


def backfill_explicit_references(db: Session) -> int:
    """Persist explicit regular prices as reusable observations.

    Safe to call repeatedly. It skips offers whose same reference value has
    already been recorded for the same product/store/source.
    """
    created = 0
    rows = db.query(OfferPriceReference).all()
    for ref in rows:
        offer = ref.offer
        if not offer or ref.reference_price <= 0 or ref.reference_type not in EXPLICIT_REFERENCE_TYPES:
            continue
        exists = (
            db.query(NormalPriceObservation)
            .filter(
                NormalPriceObservation.master_product_id == offer.master_product_id,
                NormalPriceObservation.store_id == offer.store_id,
                NormalPriceObservation.price == float(ref.reference_price),
                NormalPriceObservation.source == f"offer_ref:{ref.reference_type}",
            )
            .first()
        )
        if exists:
            continue
        add_normal_price_observation(
            db,
            master_product_id=offer.master_product_id,
            store_id=offer.store_id,
            retailer=offer.store.retailer if offer.store else None,
            price=float(ref.reference_price),
            source=f"offer_ref:{ref.reference_type}",
            confidence=1.0,
        )
        created += 1
    if created:
        db.commit()
    return created
