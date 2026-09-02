from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .db import get_db
from .feature_flags import feature_enabled, get_feature_flags
from .geo import haversine_km
from .lokero_routes import (
    _category_slug,
    _current_offers,
    _market_payload,
    _offer_payload,
    _product_payload,
)
from .models import FavoriteStore, Store
from .physical_market_identity import canonical_store_map, collapse_physical_stores
from .reviewer_auth import reviewer_device
from .services import current_user

router = APIRouter(prefix="/api/lokero", tags=["lokero-canonical-markets"])


def _released_physical_stores(db: Session, user, *, include_qa: bool = False) -> list[Store]:
    rows = collapse_physical_stores(
        db.query(Store).filter(Store.active.is_(True)).order_by(Store.city, Store.name).all()
    )
    result: list[Store] = []
    for store in rows:
        if not include_qa and not store.benchmark_verified:
            continue
        if store.latitude is None or store.longitude is None:
            continue
        if user.latitude is not None and user.longitude is not None:
            if haversine_km(user.latitude, user.longitude, store.latitude, store.longitude) > user.radius_km:
                continue
        result.append(store)
    return result


@router.get("/markets")
def canonical_markets(db: Session = Depends(get_db)):
    user = current_user(db)
    flags = get_feature_flags(db)
    if not flags["markets"]:
        return []
    include_qa = bool(reviewer_device(db))
    return [
        _market_payload(db, user, store, savings=flags["savings"])
        for store in _released_physical_stores(db, user, include_qa=include_qa)
    ]


@router.get("/offers")
def canonical_offers(
    q: str = "",
    market_ids: str = "",
    category: str = "",
    limit: int = Query(250, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    user = current_user(db)
    flags = get_feature_flags(db)
    if not flags["offers"]:
        return []
    include_qa = bool(reviewer_device(db))
    stores = _released_physical_stores(db, user, include_qa=include_qa)
    store_ids = {store.id for store in stores}
    if market_ids.strip():
        mapping = canonical_store_map(db.query(Store).all())
        requested = {
            int(value)
            for value in market_ids.split(",")
            if value.strip().isdigit()
        }
        wanted = {
            mapping.get(store_id).id if mapping.get(store_id) is not None else store_id
            for store_id in requested
        }
        store_ids &= wanted

    rows = _current_offers(db, sorted(store_ids))
    if q.strip():
        needle = q.strip().lower()
        rows = [
            row for row in rows
            if needle in (row.product.name or "").lower()
            or needle in (row.product.brand or "").lower()
        ]
    if category.strip():
        rows = [row for row in rows if _category_slug(db, row.product) == category.strip()]

    result = []
    for offer in rows[:limit]:
        result.append({
            **_offer_payload(db, offer, expose_normal_price=flags["normal_price_badges"]),
            "product": _product_payload(db, offer.product),
            "market": _market_payload(db, user, offer.store, savings=flags["savings"]),
        })
    return result


@router.get("/favorites/markets")
def canonical_favorite_markets(db: Session = Depends(get_db)):
    user = current_user(db)
    if not feature_enabled(db, "favorites"):
        return []
    mapping = canonical_store_map(db.query(Store).all())
    rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
    stores: list[Store] = []
    seen: set[int] = set()
    for row in rows:
        store = mapping.get(row.store_id, row.store)
        if not store.active or not store.benchmark_verified or store.id in seen:
            continue
        seen.add(store.id)
        stores.append(store)
    return [_market_payload(db, user, store) for store in stores]
