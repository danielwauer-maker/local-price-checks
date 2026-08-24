from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .clock import app_today
from .coverage_models import CoverageRegion
from .coverage_service import coverage_payload, stores_in_region
from .db import get_db
from .feature_flags import feature_enabled, get_feature_flags
from .geo import haversine_km
from .lokero_models import RegionInterest
from .models import (
    FavoriteProduct,
    FavoriteStore,
    MasterProduct,
    Offer,
    OfferOccurrence,
    ProductAdminData,
    ProductAlias,
    ProductCategory,
    ShoppingItem,
    Store,
)
from .normal_prices import add_normal_price_observation, reference_price_for_offer
from .offer_review_routes import QuickReviewPayload, offer_review_metadata, quick_review_offer
from .optimizer import optimize_shopping
from .reviewer_auth import (
    lock_reviewer_device,
    require_reviewer,
    reviewer_device,
    security as reviewer_security,
    unlock_reviewer_device,
)
from .services import current_user, selected_store_ids

router = APIRouter(prefix="/api/lokero", tags=["lokero"])


class RegionNotifyPayload(BaseModel):
    postalCode: str
    email: EmailStr | None = None


class ReviewerUnlockPayload(BaseModel):
    label: str | None = None
    days: int = 30


class ManualNormalPricePayload(BaseModel):
    productId: int
    storeId: int | None = None
    price: float
    notes: str | None = None


def _chain(retailer: str) -> str:
    value = (retailer or "").strip()
    if value.lower().startswith("netto"):
        return "Netto"
    if value.lower().startswith("aldi süd") or value.lower().startswith("aldi sued"):
        return "ALDI SÜD"
    if value.upper() == "PENNY":
        return "PENNY"
    return value


def _category_slug(db: Session, product: MasterProduct) -> str:
    meta = (
        db.query(ProductAdminData)
        .filter(ProductAdminData.master_product_id == product.id)
        .first()
    )
    if meta and meta.category and meta.category.active:
        return meta.category.slug
    return "sonstiges"


def _product_payload(db: Session, product: MasterProduct) -> dict:
    return {
        "id": str(product.id),
        "name": product.name,
        "brand": product.brand or "",
        "amount": product.package_size or "",
        "detail": product.package_size or "",
        "category": _category_slug(db, product),
        "ean": "",
        "tags": [],
    }


def _released_stores(db: Session, user, *, include_qa: bool = False) -> list[Store]:
    rows = db.query(Store).filter(Store.active.is_(True)).order_by(Store.city, Store.name).all()
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


def _market_payload(db: Session, user, store: Store, *, savings: bool = False) -> dict:
    distance = 0.0
    if None not in (user.latitude, user.longitude, store.latitude, store.longitude):
        distance = haversine_km(user.latitude, user.longitude, store.latitude, store.longitude)
    return {
        "id": str(store.id),
        "name": store.name,
        "chain": _chain(store.retailer),
        "street": store.address,
        "city": store.city,
        "lat": float(store.latitude or 0),
        "lng": float(store.longitude or 0),
        "openUntil": "",
        "isOpen": True,
        "distanceKm": round(distance, 1),
        "savingPotential": 0.0 if not savings else 0.0,
        "strength": "",
        "verified": bool(store.benchmark_verified),
    }


def _offer_payload(db: Session, offer: Offer, *, expose_normal_price: bool) -> dict:
    occurrence = (
        db.query(OfferOccurrence)
        .filter(OfferOccurrence.offer_id == offer.id)
        .order_by(OfferOccurrence.collected_at.desc(), OfferOccurrence.id.desc())
        .first()
    )
    normal = reference_price_for_offer(db, offer) if expose_normal_price else {
        "regularPrice": None,
        "discountPercent": None,
        "status": "disabled",
        "isRealDiscount": None,
    }
    old_price = normal.get("regularPrice")
    discount = normal.get("discountPercent") if normal.get("isRealDiscount") else None
    base_price = None
    if offer.unit_price is not None:
        unit = offer.unit_price_unit or ""
        base_price = f"{float(offer.unit_price):.2f} €/{unit}".replace(".", ",")
    return {
        "offerId": str(offer.id),
        "productId": str(offer.master_product_id),
        "marketId": str(offer.store_id),
        "price": float(offer.price),
        "oldPrice": old_price,
        "discount": round(float(discount), 0) if discount is not None else None,
        "basePrice": base_price,
        "leafletPage": occurrence.prospect_page if occurrence else None,
        "validFrom": offer.valid_from.isoformat(),
        "validUntil": offer.valid_to.isoformat(),
        "normalPriceStatus": normal.get("status"),
        "isRealDiscount": normal.get("isRealDiscount"),
    }


def _current_offers(db: Session, store_ids: list[int]) -> list[Offer]:
    if not store_ids:
        return []
    today = app_today()
    return (
        db.query(Offer)
        .filter(
            Offer.store_id.in_(store_ids),
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= today,
            Offer.valid_to >= today,
        )
        .order_by(Offer.price.asc())
        .all()
    )


def _region_state(db: Session, region: CoverageRegion) -> dict:
    raw = coverage_payload(db, region)
    stores = stores_in_region(db, region)
    released = [store for store in stores if store.benchmark_verified and store.active]
    if raw["currentOffers"] > 0 and released:
        status: Literal["available", "partial", "unavailable"] = "available"
    elif stores or released:
        status = "partial"
    else:
        status = "unavailable"
    return {
        "regionName": region.name,
        "postalCode": region.postal_code or "",
        "status": status,
        "activeMarkets": len(released),
        "totalMarkets": len(stores),
        "lastUpdated": region.updated_at.isoformat(),
        "availableRetailers": sorted({_chain(store.retailer) for store in released}),
        "coveragePercentage": round((len(released) / len(stores) * 100.0) if stores else 0.0),
        "lat": float(region.center_lat),
        "lng": float(region.center_lng),
        "currentOffers": int(raw["currentOffers"]),
    }


def _current_region(db: Session, user) -> dict:
    regions = db.query(CoverageRegion).filter(CoverageRegion.active.is_(True)).all()
    if user.latitude is not None and user.longitude is not None and regions:
        candidates = [
            (haversine_km(user.latitude, user.longitude, r.center_lat, r.center_lng), r)
            for r in regions
        ]
        candidates.sort(key=lambda row: row[0])
        distance, nearest = candidates[0]
        if distance <= max(float(nearest.radius_km), float(user.radius_km)):
            return _region_state(db, nearest)
    return {
        "regionName": user.city or "Deine Region",
        "postalCode": user.postal_code or "",
        "status": "unavailable",
        "activeMarkets": 0,
        "totalMarkets": 0,
        "lastUpdated": datetime.utcnow().isoformat(),
        "availableRetailers": [],
        "coveragePercentage": 0.0,
        "lat": float(user.latitude or 50.6199),
        "lng": float(user.longitude or 7.6264),
        "currentOffers": 0,
    }


@router.get("/features")
def features(db: Session = Depends(get_db)):
    grant = reviewer_device(db)
    return {"features": get_feature_flags(db), "reviewer": bool(grant)}


@router.get("/markets")
def markets(db: Session = Depends(get_db)):
    user = current_user(db)
    flags = get_feature_flags(db)
    if not flags["markets"]:
        return []
    include_qa = bool(reviewer_device(db))
    return [
        _market_payload(db, user, store, savings=flags["savings"])
        for store in _released_stores(db, user, include_qa=include_qa)
    ]


@router.get("/offers")
def offers(
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
    stores = _released_stores(db, user, include_qa=include_qa)
    store_ids = {store.id for store in stores}
    if market_ids.strip():
        wanted = {int(x) for x in market_ids.split(",") if x.strip().isdigit()}
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


@router.get("/offer-week")
def offer_week(db: Session = Depends(get_db)):
    user = current_user(db)
    store_ids = [store.id for store in _released_stores(db, user)]
    rows = _current_offers(db, store_ids)
    if not rows:
        today = app_today()
        return {"from": today.isoformat(), "until": today.isoformat()}
    return {
        "from": min(row.valid_from for row in rows).isoformat(),
        "until": max(row.valid_to for row in rows).isoformat(),
    }


@router.get("/weekly-savings")
def weekly_savings(db: Session = Depends(get_db)):
    user = current_user(db)
    flags = get_feature_flags(db)
    items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    if not flags["savings"] or not flags["optimization"]:
        return {
            "enabled": False,
            "amount": 0.0,
            "combinationLabel": "",
            "itemCount": len(items),
            "marketCount": 0,
            "distanceKm": 0.0,
        }
    plan = optimize_shopping(db, user, items, "current", max_stores=3)
    return {
        "enabled": True,
        "amount": round(float(plan.multi_store_saving or 0.0), 2),
        "combinationLabel": " + ".join(_chain(store.retailer) for store in plan.stores),
        "itemCount": int(plan.total_items),
        "marketCount": len(plan.stores),
        "distanceKm": round(float(plan.travel_km), 1),
    }


@router.get("/optimized-trip")
def optimized_trip(db: Session = Depends(get_db)):
    user = current_user(db)
    flags = get_feature_flags(db)
    items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    if not flags["optimization"]:
        return {"enabled": False, "stops": [], "total": 0.0, "merchandiseTotal": 0.0, "travelKm": 0.0, "travelCost": 0.0, "savings": 0.0, "itemCount": len(items)}
    plan = optimize_shopping(db, user, items, "current", max_stores=3)
    stops = []
    for store in plan.stores:
        product_ids = [str(item.master_product_id) for item, offer in plan.picks if offer and offer.store_id == store.id]
        subtotal = sum(float(offer.price) * float(item.quantity) for item, offer in plan.picks if offer and offer.store_id == store.id)
        stops.append({
            "marketId": str(store.id),
            "marketName": store.name,
            "chain": _chain(store.retailer),
            "productIds": product_ids,
            "itemCount": len(product_ids),
            "subtotal": round(subtotal, 2),
        })
    return {
        "enabled": True,
        "stops": stops,
        "total": round(float(plan.total_with_travel), 2),
        "merchandiseTotal": round(float(plan.merchandise_total), 2),
        "travelKm": round(float(plan.travel_km), 1),
        "travelCost": round(float(plan.travel_cost), 2),
        "savings": round(float(plan.multi_store_saving or 0.0), 2) if flags["savings"] else 0.0,
        "itemCount": int(plan.total_items),
    }


@router.get("/favorites/products")
def favorite_products(db: Session = Depends(get_db)):
    user = current_user(db)
    if not feature_enabled(db, "favorites"):
        return []
    rows = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).all()
    return [_product_payload(db, row.product) for row in rows]


@router.get("/favorites/markets")
def favorite_markets(db: Session = Depends(get_db)):
    user = current_user(db)
    if not feature_enabled(db, "favorites"):
        return []
    rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
    return [_market_payload(db, user, row.store) for row in rows if row.store.active]


@router.get("/search")
def search(q: str = "", db: Session = Depends(get_db)):
    needle = q.strip()
    if not needle:
        return {"categories": [], "products": []}
    category_rows = (
        db.query(ProductCategory)
        .filter(ProductCategory.active.is_(True), ProductCategory.name.ilike(f"%{needle}%"))
        .limit(8)
        .all()
    )
    aliases = (
        db.query(ProductAlias)
        .filter(ProductAlias.alias_key.ilike(f"%{needle.lower()}%"))
        .limit(30)
        .all()
    )
    alias_ids = {row.master_product_id for row in aliases}
    products = (
        db.query(MasterProduct)
        .filter(
            or_(
                MasterProduct.name.ilike(f"%{needle}%"),
                MasterProduct.brand.ilike(f"%{needle}%"),
                MasterProduct.id.in_(alias_ids) if alias_ids else False,
            )
        )
        .order_by(MasterProduct.name)
        .limit(30)
        .all()
    )
    if category_rows:
        category_ids = {row.id for row in category_rows}
        metas = db.query(ProductAdminData).filter(ProductAdminData.category_id.in_(category_ids)).limit(50).all()
        for meta in metas:
            if meta.product not in products:
                products.append(meta.product)
    categories = [
        {"id": row.slug, "label": row.name, "icon": "tag", "synonyms": []}
        for row in category_rows
    ]
    return {"categories": categories, "products": [_product_payload(db, p) for p in products[:30]]}


@router.get("/regions/status")
def region_status(db: Session = Depends(get_db)):
    if not feature_enabled(db, "region_availability"):
        raise HTTPException(status_code=404, detail="Region availability disabled")
    return _current_region(db, current_user(db))


@router.get("/regions")
def regions(q: str = "", db: Session = Depends(get_db)):
    query = db.query(CoverageRegion).filter(CoverageRegion.active.is_(True))
    if q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(or_(CoverageRegion.name.ilike(needle), CoverageRegion.postal_code.ilike(needle), CoverageRegion.city.ilike(needle)))
    return [_region_state(db, row) for row in query.order_by(CoverageRegion.name).all()]


@router.post("/regions/notify")
def notify_region(payload: RegionNotifyPayload, db: Session = Depends(get_db)):
    user = current_user(db)
    postal = payload.postalCode.strip()[:10]
    if not postal:
        raise HTTPException(status_code=400, detail="Postal code required")
    email = str(payload.email) if payload.email else None
    row = (
        db.query(RegionInterest)
        .filter(
            RegionInterest.postal_code == postal,
            RegionInterest.email == email,
            RegionInterest.user_id == user.id,
        )
        .first()
    )
    if not row:
        row = RegionInterest(postal_code=postal, email=email, user_id=user.id)
        db.add(row)
        db.commit()
    return {"ok": True, "postalCode": postal}


@router.post("/review/unlock")
def review_unlock(
    payload: ReviewerUnlockPayload,
    credentials: HTTPBasicCredentials | None = Depends(reviewer_security),
    db: Session = Depends(get_db),
):
    if not feature_enabled(db, "reviewer_mode"):
        raise HTTPException(status_code=404, detail="Not found")
    grant = unlock_reviewer_device(credentials, db, days=payload.days, label=payload.label)
    return {"ok": True, "reviewer": True, "expiresAt": grant.expires_at.isoformat(), "label": grant.label}


@router.post("/review/lock")
def review_lock(db: Session = Depends(get_db)):
    return {"ok": True, "removed": lock_reviewer_device(db)}


@router.get("/review/status")
def review_status(db: Session = Depends(get_db)):
    grant = reviewer_device(db)
    return {
        "reviewer": bool(grant),
        "expiresAt": grant.expires_at.isoformat() if grant else None,
        "label": grant.label if grant else None,
    }


@router.get("/review/offers")
def review_offers(market_ids: str = "", db: Session = Depends(get_db), actor: str = Depends(require_reviewer)):
    return offer_review_metadata(market_ids=market_ids, db=db, actor=actor)


@router.put("/review/offers/{provenance_id}")
def review_offer(provenance_id: int, payload: QuickReviewPayload, db: Session = Depends(get_db), actor: str = Depends(require_reviewer)):
    return quick_review_offer(provenance_id=provenance_id, payload=payload, db=db, actor=actor)


@router.post("/review/normal-price")
def review_normal_price(payload: ManualNormalPricePayload, db: Session = Depends(get_db), actor: str = Depends(require_reviewer)):
    product = db.get(MasterProduct, payload.productId)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    store = db.get(Store, payload.storeId) if payload.storeId else None
    if payload.price <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")
    row = add_normal_price_observation(
        db,
        master_product_id=product.id,
        store_id=store.id if store else None,
        retailer=store.retailer if store else None,
        price=payload.price,
        source="reviewer_manual",
        confidence=1.0,
        notes=payload.notes,
    )
    db.flush()
    db.commit()
    return {"ok": True, "id": row.id}
