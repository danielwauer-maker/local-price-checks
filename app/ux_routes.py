from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from .clock import app_today
from .config import settings
from .db import Base, get_db
from .geo import haversine_km, resolve_center
from .models import FavoriteProduct, MasterProduct, ShoppingItem, Store
from .optimizer import optimize_shopping
from .services import current_user

router = APIRouter(prefix="/api/ux")


class ShoppingItemCheck(Base):
    __tablename__ = "shopping_item_checks"
    __table_args__ = (UniqueConstraint("user_id", "master_product_id", name="uq_shopping_item_check"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    checked: Mapped[bool] = mapped_column(Boolean, default=True)


class ProfilePayload(BaseModel):
    display_name: str
    postal_code: str
    city: str


class CheckedPayload(BaseModel):
    checked: bool


@router.get("/bootstrap")
def ux_bootstrap(db: Session = Depends(get_db)):
    user = current_user(db)
    favorites = [str(x.master_product_id) for x in db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).all()]
    checked = [str(x.master_product_id) for x in db.query(ShoppingItemCheck).filter(ShoppingItemCheck.user_id == user.id, ShoppingItemCheck.checked.is_(True)).all()]
    return {
        "profile": {"displayName": user.display_name, "postalCode": user.postal_code or "", "city": user.city or ""},
        "productFavorites": favorites,
        "checked": checked,
    }


@router.put("/profile")
def update_profile(payload: ProfilePayload, db: Session = Depends(get_db)):
    user = current_user(db)
    user.display_name = payload.display_name.strip() or "Local User"
    user.postal_code = payload.postal_code.strip() or None
    user.city = payload.city.strip() or None
    if user.postal_code and user.city:
        center = resolve_center(user.postal_code, user.city)
        if center:
            user.latitude, user.longitude = center
    db.commit()
    return {"ok": True, "label": f"{user.postal_code or ''} {user.city or ''}".strip(), "lat": user.latitude, "lng": user.longitude}


@router.post("/favorites/{product_id}/toggle")
def toggle_product_favorite(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    if not db.get(MasterProduct, product_id):
        raise HTTPException(404, "Product not found")
    row = db.query(FavoriteProduct).filter_by(user_id=user.id, master_product_id=product_id).first()
    if row:
        db.delete(row)
        active = False
    else:
        db.add(FavoriteProduct(user_id=user.id, master_product_id=product_id))
        active = True
    db.commit()
    return {"active": active}


@router.put("/checked/{product_id}")
def set_checked(product_id: int, payload: CheckedPayload, db: Session = Depends(get_db)):
    user = current_user(db)
    row = db.query(ShoppingItemCheck).filter_by(user_id=user.id, master_product_id=product_id).first()
    if payload.checked:
        if row:
            row.checked = True
        else:
            db.add(ShoppingItemCheck(user_id=user.id, master_product_id=product_id, checked=True))
    elif row:
        db.delete(row)
    db.commit()
    return {"productId": str(product_id), "checked": payload.checked}


@router.delete("/checked")
def clear_checked(db: Session = Depends(get_db)):
    user = current_user(db)
    db.query(ShoppingItemCheck).filter(ShoppingItemCheck.user_id == user.id).delete()
    db.commit()
    return {"ok": True}


def _netto_prospect_url(store: Store, offset_weeks: int = 0) -> str | None:
    if store.retailer != "Netto Marken-Discount" or not store.external_id:
        return None
    target = app_today() + timedelta(days=7 * offset_weeks)
    week = target.isocalendar().week
    return f"https://wochenprospekt.netto-online.de/hz{week:02d}_kess/?storeid={store.external_id}"


@router.get("/stores/{store_id}")
def store_detail(store_id: int, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if not store or not store.active:
        raise HTTPException(404, "Market not found")
    current = _netto_prospect_url(store, 0) or store.source_url
    direct_future = _netto_prospect_url(store, 1)
    # For retailers with a combined official offer/prospect page, reuse the
    # official page as future entry point; the user can select "next week" there.
    future = direct_future or store.source_url
    lat = store.latitude
    lng = store.longitude
    google = None
    apple = None
    osm = None
    if lat is not None and lng is not None:
        google = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
        apple = f"https://maps.apple.com/?daddr={lat},{lng}&dirflg=d"
        osm = f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=;{lat},{lng}"
    return {
        "id": str(store.id),
        "name": store.name,
        "chain": store.retailer,
        "address": f"{store.address}, {store.postal_code} {store.city}",
        "lat": lat,
        "lng": lng,
        "currentProspectUrl": current,
        "futureProspectUrl": future,
        "futureProspectDirect": bool(direct_future),
        "directions": {"google": google, "apple": apple, "osm": osm},
    }


@router.get("/route-plan")
def route_plan(max_stores: int = 2, db: Session = Depends(get_db)):
    user = current_user(db)
    items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    plan = optimize_shopping(db, user, items, "current", max_stores=max(1, min(max_stores, 3)))
    if user.latitude is None or user.longitude is None or not plan.stores:
        return {"legs": [], "googleMapsUrl": None, "totalKm": 0.0}

    remaining = [s for s in plan.stores if s.latitude is not None and s.longitude is not None]
    cur_lat, cur_lng = user.latitude, user.longitude
    cur_name = f"{user.postal_code or ''} {user.city or ''}".strip() or "Start"
    legs = []
    ordered = []
    while remaining:
        nxt = min(remaining, key=lambda s: haversine_km(cur_lat, cur_lng, s.latitude, s.longitude))
        km = haversine_km(cur_lat, cur_lng, nxt.latitude, nxt.longitude) * settings.route_distance_factor
        legs.append({"from": cur_name, "to": nxt.name, "km": round(km, 1)})
        ordered.append(nxt)
        cur_lat, cur_lng, cur_name = nxt.latitude, nxt.longitude, nxt.name
        remaining.remove(nxt)
    return_km = haversine_km(cur_lat, cur_lng, user.latitude, user.longitude) * settings.route_distance_factor
    legs.append({"from": cur_name, "to": f"{user.postal_code or ''} {user.city or ''}".strip() or "Start", "km": round(return_km, 1)})

    origin = f"{user.latitude},{user.longitude}"
    waypoints = "|".join(f"{s.latitude},{s.longitude}" for s in ordered)
    google = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={origin}&waypoints={quote(waypoints, safe='|,')}&travelmode=driving"
    return {"legs": legs, "googleMapsUrl": google, "totalKm": round(sum(x["km"] for x in legs), 1)}
