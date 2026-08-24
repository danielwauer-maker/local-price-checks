from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .clock import app_today
from .db import get_db
from .feature_flags import feature_enabled
from .geo import haversine_km
from .lokero_models import FavoriteProductPreference
from .models import FavoriteProduct, MasterProduct, Offer, ProductAdminData, Store
from .services import current_user

router = APIRouter(prefix="/api/lokero/favorites", tags=["lokero-favorites"])


class FavoritePreferencePayload(BaseModel):
    allowAlternatives: bool


def _category_slug(db: Session, product_id: int) -> str:
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product_id).first()
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
        "category": _category_slug(db, product.id),
        "ean": "",
        "tags": [],
        "imageUrl": f"/api/lokero/product-media/{product.id}",
    }


def _public_store_ids(db: Session, user) -> list[int]:
    rows = db.query(Store).filter(Store.active.is_(True), Store.benchmark_verified.is_(True)).all()
    result: list[int] = []
    for store in rows:
        if store.latitude is None or store.longitude is None:
            continue
        if user.latitude is not None and user.longitude is not None:
            if haversine_km(user.latitude, user.longitude, store.latitude, store.longitude) > user.radius_km:
                continue
        result.append(store.id)
    return result


@router.get("/preferences")
def favorite_preferences(db: Session = Depends(get_db)):
    user = current_user(db)
    rows = db.query(FavoriteProductPreference).filter(FavoriteProductPreference.user_id == user.id).all()
    return {str(row.master_product_id): bool(row.allow_alternatives) for row in rows}


@router.get("/products/{product_id}/preferences")
def favorite_product_preference(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    favorite = db.query(FavoriteProduct).filter(
        FavoriteProduct.user_id == user.id,
        FavoriteProduct.master_product_id == product_id,
    ).first()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")
    row = db.query(FavoriteProductPreference).filter(
        FavoriteProductPreference.user_id == user.id,
        FavoriteProductPreference.master_product_id == product_id,
    ).first()
    return {"productId": str(product_id), "allowAlternatives": bool(row.allow_alternatives) if row else False}


@router.put("/products/{product_id}/preferences")
def update_favorite_product_preference(
    product_id: int,
    payload: FavoritePreferencePayload,
    db: Session = Depends(get_db),
):
    user = current_user(db)
    favorite = db.query(FavoriteProduct).filter(
        FavoriteProduct.user_id == user.id,
        FavoriteProduct.master_product_id == product_id,
    ).first()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")
    row = db.query(FavoriteProductPreference).filter(
        FavoriteProductPreference.user_id == user.id,
        FavoriteProductPreference.master_product_id == product_id,
    ).first()
    if not row:
        row = FavoriteProductPreference(user_id=user.id, master_product_id=product_id)
        db.add(row)
    row.allow_alternatives = bool(payload.allowAlternatives)
    db.commit()
    return {"productId": str(product_id), "allowAlternatives": bool(row.allow_alternatives)}


@router.get("/products/{product_id}/alternatives")
def favorite_product_alternatives(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    if not feature_enabled(db, "product_alternatives"):
        return []
    favorite = db.query(FavoriteProduct).filter(
        FavoriteProduct.user_id == user.id,
        FavoriteProduct.master_product_id == product_id,
    ).first()
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")
    pref = db.query(FavoriteProductPreference).filter(
        FavoriteProductPreference.user_id == user.id,
        FavoriteProductPreference.master_product_id == product_id,
    ).first()
    if not pref or not pref.allow_alternatives:
        return []

    category = _category_slug(db, product_id)
    if category == "sonstiges":
        return []
    store_ids = _public_store_ids(db, user)
    if not store_ids:
        return []
    today = app_today()
    offers = db.query(Offer).filter(
        Offer.store_id.in_(store_ids),
        Offer.local_store_offer.is_(True),
        Offer.valid_from <= today,
        Offer.valid_to >= today,
        Offer.master_product_id != product_id,
    ).order_by(Offer.price.asc()).all()

    seen: set[int] = set()
    result = []
    for offer in offers:
        if offer.master_product_id in seen:
            continue
        if _category_slug(db, offer.master_product_id) != category:
            continue
        seen.add(offer.master_product_id)
        result.append({
            "product": _product_payload(db, offer.product),
            "price": float(offer.price),
            "market": {
                "id": str(offer.store.id),
                "name": offer.store.name,
                "chain": offer.store.retailer,
            },
            "kind": "aehnlich",
            "reason": "Gleiche Produktkategorie und aktuell im Angebot",
        })
        if len(result) >= 5:
            break
    return result
