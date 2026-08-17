from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, get_db
from .geo import resolve_center
from .models import FavoriteProduct, MasterProduct, Store
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
        db.delete(row); active = False
    else:
        db.add(FavoriteProduct(user_id=user.id, master_product_id=product_id)); active = True
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


@router.get("/stores/{store_id}")
def store_detail(store_id: int, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if not store or not store.active:
        raise HTTPException(404, "Market not found")
    return {
        "id": str(store.id),
        "name": store.name,
        "chain": store.retailer,
        "address": f"{store.address}, {store.postal_code} {store.city}",
        "lat": store.latitude,
        "lng": store.longitude,
        "currentProspectUrl": store.source_url,
        "futureProspectUrl": None,
    }
