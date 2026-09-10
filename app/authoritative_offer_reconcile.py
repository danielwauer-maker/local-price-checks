from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .admin_learning import resolve_product_alias
from .engine_v140.product_cleaning import clean_product_name
from .extractor_adapter import normalize_master_key
from .models import MasterProduct, Offer, Store
from .physical_market_identity import canonical_store_map


def _date(value: str | None):
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _physical_store_ids(db: Session, store: Store) -> list[int]:
    rows = db.query(Store).filter(Store.retailer == store.retailer).all()
    mapping = canonical_store_map(rows)
    canonical = mapping.get(store.id, store)
    return [row.id for row in rows if mapping.get(row.id, row).id == canonical.id]


def reconcile_rewe_authoritative_snapshot(db: Session, store: Store, rows: list) -> int:
    """Deactivate stale current REWE offers after one complete authoritative snapshot.

    This is deliberately conservative: callers must only invoke it after a
    technically clean production collection whose rows were all admitted.  No
    offer, occurrence or provenance row is deleted.  Offers absent from the
    fresh snapshot are merely marked ``local_store_offer=False`` and are
    automatically reactivated by the normal importer if they reappear later.
    """
    if store.retailer != "REWE" or not rows:
        return 0

    store_ids = _physical_store_ids(db, store)
    active_offer_ids: set[int] = set()
    periods: set[tuple] = set()

    for row in rows:
        valid_from = _date(getattr(row, "valid_from", None))
        valid_to = _date(getattr(row, "valid_to", None))
        price = getattr(row, "price", None)
        name = clean_product_name(getattr(row, "product_name", "") or "")
        if not valid_from or not valid_to or valid_to < valid_from or price is None or not name:
            return 0

        periods.add((valid_from, valid_to))
        key = normalize_master_key(name, getattr(row, "quantity", None), getattr(row, "unit", None))
        product = resolve_product_alias(db, key)
        if not product:
            product = db.query(MasterProduct).filter(MasterProduct.normalized_key == key).first()
        if not product:
            # The import immediately preceding reconciliation should have
            # created/resolved every admitted product.  Missing identity means
            # we cannot prove snapshot completeness, so fail closed.
            return 0

        matches = (
            db.query(Offer)
            .filter(
                Offer.store_id.in_(store_ids),
                Offer.master_product_id == product.id,
                Offer.valid_from == valid_from,
                Offer.valid_to == valid_to,
                Offer.price == float(price),
            )
            .all()
        )
        if not matches:
            return 0
        active_offer_ids.update(offer.id for offer in matches)

    if not active_offer_ids or not periods:
        return 0

    stale: list[Offer] = []
    for valid_from, valid_to in periods:
        stale.extend(
            db.query(Offer)
            .filter(
                Offer.store_id.in_(store_ids),
                Offer.valid_from == valid_from,
                Offer.valid_to == valid_to,
                Offer.local_store_offer.is_(True),
                ~Offer.id.in_(active_offer_ids),
            )
            .all()
        )

    unique = {offer.id: offer for offer in stale}
    for offer in unique.values():
        offer.local_store_offer = False
    if unique:
        db.commit()
    return len(unique)
