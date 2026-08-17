from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .clock import app_today
from .db import get_db
from .geo import haversine_km
from .models import FavoriteStore, MasterProduct, MediaAsset, Offer, ProductAdminData, ProductBarcode, ShoppingItem, Store
from .optimizer import optimize_shopping
from .services import current_user, selected_store_ids

router = APIRouter(prefix="/api")


class QuantityPayload(BaseModel):
    quantity: float


class LocationPayload(BaseModel):
    lat: float
    lng: float
    label: str = "Mein Standort"
    radius: float | None = None


def _primary_media(db: Session, *, kind: str, product_id: int | None = None, store_id: int | None = None, retailer: str | None = None) -> str | None:
    q = db.query(MediaAsset).filter(MediaAsset.kind == kind, MediaAsset.active.is_(True))
    if product_id is not None:
        q = q.filter(MediaAsset.master_product_id == product_id)
    if store_id is not None:
        q = q.filter(MediaAsset.store_id == store_id)
    if retailer is not None:
        q = q.filter(MediaAsset.retailer == retailer)
    row = q.order_by(MediaAsset.is_primary.desc(), MediaAsset.created_at.desc()).first()
    if not row:
        return None
    return f"/media/{row.file_path}" if row.file_path else row.source_url


def _market(db: Session, store: Store) -> dict:
    return {
        "id": str(store.id),
        "name": store.name,
        "chain": store.retailer,
        "street": store.address,
        "city": store.city,
        "lat": store.latitude,
        "lng": store.longitude,
        "openUntil": "",
        "rating": 0,
        "verified": bool(store.benchmark_verified),
        "imageUrl": _primary_media(db, kind="store", store_id=store.id),
        "logoUrl": _primary_media(db, kind="retailer_logo", retailer=store.retailer),
    }


def _product(db: Session, product: MasterProduct, barcode: str = "") -> dict:
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product.id).first()
    category = meta.category.name if meta and meta.category else "Sonstiges"
    return {
        "id": str(product.id),
        "name": product.name,
        "brand": product.brand or "",
        "category": category,
        "unit": product.package_size or "",
        "ean": barcode,
        "emoji": "🏷️",
        "imageUrl": _primary_media(db, kind="product", product_id=product.id),
    }


def _stores_in_radius(db: Session, user) -> list[Store]:
    stores = db.query(Store).filter(Store.active.is_(True)).order_by(Store.city, Store.name).all()
    rows: list[Store] = []
    for store in stores:
        if store.latitude is None or store.longitude is None:
            continue
        if user.latitude is not None and user.longitude is not None:
            distance = haversine_km(user.latitude, user.longitude, store.latitude, store.longitude)
            if distance > user.radius_km:
                continue
        rows.append(store)
    return rows


def _current_offer_rows(db: Session, store_ids: list[int]) -> list[Offer]:
    if not store_ids:
        return []
    today = app_today()
    return db.query(Offer).filter(Offer.store_id.in_(store_ids), Offer.local_store_offer.is_(True), Offer.valid_from <= today, Offer.valid_to >= today).order_by(Offer.price.asc()).all()


def _price_payload(offer: Offer) -> dict:
    return {
        "productId": str(offer.master_product_id),
        "marketId": str(offer.store_id),
        "price": float(offer.price),
        "offer": {"price": float(offer.price), "until": offer.valid_to.strftime("%d.%m.")},
        "validFrom": offer.valid_from.isoformat(),
        "validTo": offer.valid_to.isoformat(),
        "unitPrice": float(offer.unit_price) if offer.unit_price is not None else None,
        "unitPriceUnit": offer.unit_price_unit,
    }


def _plan_payload(db: Session, user, max_stores: int) -> dict:
    items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    plan = optimize_shopping(db, user, items, "current", max_stores=max_stores)
    stops = []
    for store in plan.stores:
        lines = []
        subtotal = 0.0
        for item, offer in plan.picks:
            if offer is None or offer.store_id != store.id:
                continue
            line_total = float(offer.price) * float(item.quantity)
            subtotal += line_total
            lines.append({"product": _product(db, item.product), "qty": float(item.quantity), "unitPrice": float(offer.price), "isOffer": True, "lineTotal": round(line_total, 2), "saved": 0.0})
        stops.append({"market": _market(db, store), "lines": lines, "total": round(subtotal, 2)})
    missing = [{"product": _product(db, item.product), "qty": float(item.quantity)} for item, offer in plan.picks if offer is None]
    single_market = None
    if plan.single_store_name:
        store = db.query(Store).filter(Store.name == plan.single_store_name).first()
        if store:
            single_market = _market(db, store)
    return {
        "stops": stops,
        "total": round(float(plan.total_with_travel), 2),
        "merchandiseTotal": round(float(plan.merchandise_total), 2),
        "travelKm": round(float(plan.travel_km), 2),
        "travelCost": round(float(plan.travel_cost), 2),
        "singleMarketTotal": round(float(plan.single_store_total or 0), 2),
        "singleMarket": single_market,
        "worstTotal": round(float(plan.single_store_total or 0), 2),
        "savingsVsSingle": round(float(plan.multi_store_saving or 0), 2),
        "savingsVsWorst": round(float(plan.multi_store_saving or 0), 2),
        "offeredItems": int(plan.covered_items),
        "availableItems": int(plan.offered_items),
        "totalItems": int(plan.total_items),
        "missing": missing,
    }


@router.get("/bootstrap")
def bootstrap(db: Session = Depends(get_db)):
    user = current_user(db)
    selected = [str(store_id) for store_id in selected_store_ids(db, user)]
    stores = _stores_in_radius(db, user)
    store_ids = [store.id for store in stores]
    products = db.query(MasterProduct).order_by(MasterProduct.name).all()
    barcode_by_product: dict[int, str] = {}
    for row in db.query(ProductBarcode).all():
        barcode_by_product.setdefault(row.master_product_id, row.barcode)
    prices = [_price_payload(o) for o in _current_offer_rows(db, store_ids)]
    basket_rows = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    basket = {str(row.master_product_id): float(row.quantity) for row in basket_rows}
    return {
        "location": {"lat": user.latitude or 50.6199, "lng": user.longitude or 7.6264, "label": f"{user.postal_code or ''} {user.city or ''}".strip() or "Standort einrichten"},
        "radius": float(user.radius_km),
        "selected": selected,
        "favorites": selected,
        "basket": basket,
        "markets": [_market(db, s) for s in stores],
        "products": [_product(db, p, barcode_by_product.get(p.id, "")) for p in products],
        "prices": prices,
    }


@router.get("/plan")
def shopping_plan(max_stores: int = 2, db: Session = Depends(get_db)):
    user = current_user(db)
    return _plan_payload(db, user, max(1, min(int(max_stores), 3)))


@router.get("/products")
def product_search(q: str = "", db: Session = Depends(get_db)):
    query = db.query(MasterProduct)
    if q.strip():
        query = query.filter(MasterProduct.name.ilike(f"%{q.strip()}%"))
    return [_product(db, p) for p in query.order_by(MasterProduct.name).limit(50).all()]


@router.post("/stores/{store_id}/toggle")
def toggle_store(store_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    store = db.get(Store, store_id)
    if not store or not store.active or not store.benchmark_verified:
        raise HTTPException(status_code=404, detail="Market not available")
    row = db.query(FavoriteStore).filter_by(user_id=user.id, store_id=store_id).first()
    if row:
        db.delete(row); selected = False
    else:
        db.add(FavoriteStore(user_id=user.id, store_id=store_id)); selected = True
    db.commit()
    return {"selected": selected, "selectedIds": [str(x) for x in selected_store_ids(db, user)]}


@router.put("/basket/{product_id}")
def set_basket_quantity(product_id: int, payload: QuantityPayload, db: Session = Depends(get_db)):
    user = current_user(db)
    product = db.get(MasterProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    item = db.query(ShoppingItem).filter_by(user_id=user.id, master_product_id=product_id).first()
    quantity = max(0.0, min(float(payload.quantity), 999.0))
    if quantity <= 0:
        if item: db.delete(item)
    elif item:
        item.quantity = quantity
    else:
        db.add(ShoppingItem(user_id=user.id, master_product_id=product_id, quantity=quantity))
    db.commit()
    return {"productId": str(product_id), "quantity": quantity}


@router.delete("/basket")
def clear_basket(db: Session = Depends(get_db)):
    user = current_user(db)
    db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).delete()
    db.commit()
    return {"ok": True}


@router.put("/location")
def save_location(payload: LocationPayload, db: Session = Depends(get_db)):
    user = current_user(db)
    user.latitude = payload.lat; user.longitude = payload.lng
    if payload.label and payload.label != "Mein Standort":
        parts = payload.label.strip().split(maxsplit=1)
        if parts and parts[0].isdigit():
            user.postal_code = parts[0]
            if len(parts) > 1: user.city = parts[1]
    if payload.radius is not None:
        user.radius_km = max(1.0, min(float(payload.radius), 50.0))
    db.commit()
    return {"ok": True}
