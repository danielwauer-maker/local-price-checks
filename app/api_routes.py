from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import FavoriteStore, MasterProduct, Offer, ProductBarcode, ShoppingItem, Store
from .services import current_user, offers_for_selected_stores

router = APIRouter(prefix="/api")


class QuantityPayload(BaseModel):
    quantity: float


class LocationPayload(BaseModel):
    lat: float
    lng: float
    label: str = "Mein Standort"
    radius: float | None = None


def _market(store: Store) -> dict:
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
    }


def _product(product: MasterProduct, barcode: str = "") -> dict:
    return {
        "id": str(product.id),
        "name": product.name,
        "brand": product.brand or "",
        "category": "Grundnahrung",
        "unit": product.package_size or "",
        "ean": barcode,
        "emoji": "🏷️",
    }


@router.get("/bootstrap")
def bootstrap(db: Session = Depends(get_db)):
    user = current_user(db)
    selected_rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
    selected = [str(row.store_id) for row in selected_rows]

    stores = db.query(Store).filter(Store.active.is_(True)).order_by(Store.city, Store.name).all()
    products = db.query(MasterProduct).order_by(MasterProduct.name).all()
    barcode_by_product: dict[int, str] = {}
    for row in db.query(ProductBarcode).all():
        barcode_by_product.setdefault(row.master_product_id, row.barcode)

    current = offers_for_selected_stores(db, user, "current")
    prices = [
        {
            "productId": str(o.master_product_id),
            "marketId": str(o.store_id),
            "price": float(o.price),
            "offer": {"price": float(o.price), "until": o.valid_to.strftime("%d.%m.")},
            "validFrom": o.valid_from.isoformat(),
            "validTo": o.valid_to.isoformat(),
        }
        for o in current
    ]

    basket_rows = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    basket = {str(row.master_product_id): float(row.quantity) for row in basket_rows}

    return {
        "location": {
            "lat": user.latitude or 50.6199,
            "lng": user.longitude or 7.6264,
            "label": f"{user.postal_code or ''} {user.city or ''}".strip() or "Standort einrichten",
        },
        "radius": float(user.radius_km),
        "selected": selected,
        "favorites": selected,
        "basket": basket,
        "markets": [_market(s) for s in stores if s.latitude is not None and s.longitude is not None],
        "products": [_product(p, barcode_by_product.get(p.id, "")) for p in products],
        "prices": prices,
    }


@router.get("/products")
def product_search(q: str = "", db: Session = Depends(get_db)):
    query = db.query(MasterProduct)
    if q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(MasterProduct.name.ilike(needle))
    products = query.order_by(MasterProduct.name).limit(50).all()
    return [_product(p) for p in products]


@router.post("/stores/{store_id}/toggle")
def toggle_store(store_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    store = db.get(Store, store_id)
    if not store or not store.active or not store.benchmark_verified:
        raise HTTPException(status_code=404, detail="Market not available")
    row = db.query(FavoriteStore).filter_by(user_id=user.id, store_id=store_id).first()
    if row:
        db.delete(row)
        selected = False
    else:
        db.add(FavoriteStore(user_id=user.id, store_id=store_id))
        selected = True
    db.commit()
    return {"selected": selected}


@router.put("/basket/{product_id}")
def set_basket_quantity(product_id: int, payload: QuantityPayload, db: Session = Depends(get_db)):
    user = current_user(db)
    product = db.get(MasterProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    item = db.query(ShoppingItem).filter_by(user_id=user.id, master_product_id=product_id).first()
    quantity = max(0.0, min(float(payload.quantity), 999.0))
    if quantity <= 0:
        if item:
            db.delete(item)
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
    user.latitude = payload.lat
    user.longitude = payload.lng
    if payload.label and payload.label != "Mein Standort":
        parts = payload.label.strip().split(maxsplit=1)
        if parts and parts[0].isdigit():
            user.postal_code = parts[0]
            if len(parts) > 1:
                user.city = parts[1]
    if payload.radius is not None:
        user.radius_km = max(1.0, min(float(payload.radius), 50.0))
    db.commit()
    return {"ok": True}
