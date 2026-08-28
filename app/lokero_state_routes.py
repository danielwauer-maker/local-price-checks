from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .account_realtime import publish_account_event
from .db import get_db
from .feature_flags import feature_enabled
from .models import FavoriteProduct, MasterProduct
from .services import current_user

router = APIRouter(prefix="/api/lokero", tags=["lokero-state"])


@router.put("/favorites/products/{product_id}")
def add_favorite_product(product_id: int, db: Session = Depends(get_db)):
    if not feature_enabled(db, "favorites"):
        raise HTTPException(status_code=404, detail="Favorites disabled")
    user = current_user(db)
    product = db.get(MasterProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    row = (
        db.query(FavoriteProduct)
        .filter_by(user_id=user.id, master_product_id=product_id)
        .first()
    )
    changed = False
    if not row:
        db.add(FavoriteProduct(user_id=user.id, master_product_id=product_id))
        db.commit()
        changed = True
    if changed:
        publish_account_event(user.id, "favorites")
    return {"ok": True, "favorite": True, "productId": str(product_id)}


@router.delete("/favorites/products/{product_id}")
def remove_favorite_product(product_id: int, db: Session = Depends(get_db)):
    if not feature_enabled(db, "favorites"):
        raise HTTPException(status_code=404, detail="Favorites disabled")
    user = current_user(db)
    row = (
        db.query(FavoriteProduct)
        .filter_by(user_id=user.id, master_product_id=product_id)
        .first()
    )
    changed = False
    if row:
        db.delete(row)
        db.commit()
        changed = True
    if changed:
        publish_account_event(user.id, "favorites")
    return {"ok": True, "favorite": False, "productId": str(product_id)}
