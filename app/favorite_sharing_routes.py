from __future__ import annotations

import io
import secrets
from datetime import datetime
from typing import Iterable

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .clock import app_today
from .db import get_db
from .lokero_models import FavoriteShare, FavoriteShareItemVisibility, FavoriteShareSubscription
from .models import FavoriteProduct, MasterProduct, Offer, Store
from .services import current_user, selected_store_ids
from .shopping_sharing_routes import _display_name, _linked_identity, _product_payload, _require_linked_user

router = APIRouter(prefix="/api/sharing", tags=["sharing"])


class ShareEnabledPayload(BaseModel):
    enabled: bool


class FavoriteVisibilityPayload(BaseModel):
    visible: bool


class SubscriptionSettingsPayload(BaseModel):
    inAppEnabled: bool | None = None
    pushEnabled: bool | None = None


def _get_or_create_share(db: Session, user_id: int) -> FavoriteShare:
    row = db.query(FavoriteShare).filter(FavoriteShare.owner_user_id == user_id).first()
    if row is None:
        row = FavoriteShare(owner_user_id=user_id, token=secrets.token_urlsafe(24), enabled=True)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _favorite_visibility_map(db: Session, user_id: int) -> dict[int, bool]:
    rows = db.query(FavoriteShareItemVisibility).filter(FavoriteShareItemVisibility.owner_user_id == user_id).all()
    return {row.master_product_id: bool(row.visible) for row in rows}


def _visible_favorite_ids(db: Session, owner_user_id: int) -> list[int]:
    visibility = _favorite_visibility_map(db, owner_user_id)
    rows = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == owner_user_id).all()
    return [row.master_product_id for row in rows if visibility.get(row.master_product_id, True)]


def _share_payload(db: Session, share: FavoriteShare, *, include_token: bool) -> dict:
    owner = db.get(type(share.owner), share.owner_user_id) if share.owner is not None else share.owner
    favorite_rows = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == share.owner_user_id).all()
    visibility = _favorite_visibility_map(db, share.owner_user_id)
    payload = {
        "enabled": bool(share.enabled),
        "ownerName": _display_name(owner),
        "visibleCount": sum(1 for row in favorite_rows if visibility.get(row.master_product_id, True)),
        "items": [
            {
                "productId": str(row.master_product_id),
                "visible": visibility.get(row.master_product_id, True),
                "product": _product_payload(db, db.get(MasterProduct, row.master_product_id)),
            }
            for row in favorite_rows
        ],
    }
    if include_token:
        payload["token"] = share.token
    return payload


@router.get("/favorites/settings")
def favorite_share_settings(db: Session = Depends(get_db)):
    user = current_user(db, persist=False)
    identity = _linked_identity(db, user)
    if identity is None:
        return {"enabledForAccount": False, "share": None}
    share = db.query(FavoriteShare).filter(FavoriteShare.owner_user_id == user.id).first()
    return {"enabledForAccount": True, "share": _share_payload(db, share, include_token=True) if share else None}


@router.post("/favorites/share")
def enable_favorite_share(payload: ShareEnabledPayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    share = _get_or_create_share(db, user.id)
    share.enabled = payload.enabled
    share.updated_at = datetime.utcnow()
    db.commit()
    return _share_payload(db, share, include_token=True)


@router.post("/favorites/share/rotate")
def rotate_favorite_share(db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    share = _get_or_create_share(db, user.id)
    share.token = secrets.token_urlsafe(24)
    share.enabled = True
    share.updated_at = datetime.utcnow()
    db.commit()
    return _share_payload(db, share, include_token=True)


@router.put("/favorites/items/{product_id}/visibility")
def set_favorite_visibility(product_id: int, payload: FavoriteVisibilityPayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    favorite = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id, FavoriteProduct.master_product_id == product_id).first()
    if favorite is None:
        raise HTTPException(status_code=404, detail="Produkt ist kein Favorit.")
    row = db.query(FavoriteShareItemVisibility).filter(FavoriteShareItemVisibility.owner_user_id == user.id, FavoriteShareItemVisibility.master_product_id == product_id).first()
    if row is None:
        row = FavoriteShareItemVisibility(owner_user_id=user.id, master_product_id=product_id, visible=payload.visible)
        db.add(row)
    else:
        row.visible = payload.visible
        row.updated_at = datetime.utcnow()
    db.commit()
    share = db.query(FavoriteShare).filter(FavoriteShare.owner_user_id == user.id).first()
    return {"visible": payload.visible, "share": _share_payload(db, share, include_token=True) if share else None}


@router.get("/favorites/public/{token}")
def public_favorites(token: str, db: Session = Depends(get_db)):
    share = db.query(FavoriteShare).filter(FavoriteShare.token == token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    owner = share.owner
    if not share.enabled:
        return {"available": False, "ownerName": _display_name(owner), "items": []}
    ids = _visible_favorite_ids(db, share.owner_user_id)
    products = [db.get(MasterProduct, product_id) for product_id in ids]
    return {"available": True, "ownerName": _display_name(owner), "items": [_product_payload(db, product) for product in products if product is not None]}


@router.get("/favorites/public/{token}/qr.svg")
def favorite_share_qr(token: str, request: Request, db: Session = Depends(get_db)):
    share = db.query(FavoriteShare).filter(FavoriteShare.token == token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    public_url = f"{str(request.base_url).rstrip('/')}/favoriten/geteilt/{share.token}"
    image = qrcode.make(public_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=300"})


@router.post("/favorites/subscriptions/{token}")
def subscribe_favorites(token: str, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    share = db.query(FavoriteShare).filter(FavoriteShare.token == token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    if share.owner_user_id == user.id:
        raise HTTPException(status_code=400, detail="Die eigenen Favoriten können nicht als Freund gespeichert werden.")
    row = db.query(FavoriteShareSubscription).filter(FavoriteShareSubscription.subscriber_user_id == user.id, FavoriteShareSubscription.share_id == share.id).first()
    if row is None:
        db.add(FavoriteShareSubscription(subscriber_user_id=user.id, share_id=share.id, in_app_enabled=True, push_enabled=False))
        db.commit()
    return {"subscribed": True}


@router.delete("/favorites/subscriptions/{share_id}")
def unsubscribe_favorites(share_id: int, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    row = db.query(FavoriteShareSubscription).filter(FavoriteShareSubscription.subscriber_user_id == user.id, FavoriteShareSubscription.share_id == share_id).first()
    if row:
        db.delete(row)
        db.commit()
    return {"subscribed": False}


@router.patch("/favorites/subscriptions/{share_id}")
def update_subscription(share_id: int, payload: SubscriptionSettingsPayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    row = db.query(FavoriteShareSubscription).filter(FavoriteShareSubscription.subscriber_user_id == user.id, FavoriteShareSubscription.share_id == share_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Freundesfavoriten nicht gespeichert.")
    if payload.inAppEnabled is not None:
        row.in_app_enabled = payload.inAppEnabled
    if payload.pushEnabled is not None:
        row.push_enabled = payload.pushEnabled
    db.commit()
    return {"inAppEnabled": row.in_app_enabled, "pushEnabled": row.push_enabled}


def _friend_offer_matches(db: Session, subscriber, subscriptions: Iterable[FavoriteShareSubscription]) -> list[dict]:
    selected_ids = selected_store_ids(db, subscriber)
    if not selected_ids:
        return []
    today = app_today()
    current_offers = db.query(Offer).filter(Offer.store_id.in_(selected_ids), Offer.local_store_offer.is_(True), Offer.valid_from <= today, Offer.valid_to >= today).all()
    by_product: dict[int, Offer] = {}
    for offer in current_offers:
        current = by_product.get(offer.master_product_id)
        if current is None or float(offer.price) < float(current.price):
            by_product[offer.master_product_id] = offer

    alerts: list[dict] = []
    for sub in subscriptions:
        share = db.get(FavoriteShare, sub.share_id)
        if share is None or not share.enabled:
            continue
        owner = share.owner
        for product_id in _visible_favorite_ids(db, share.owner_user_id):
            offer = by_product.get(product_id)
            if offer is None:
                continue
            product = db.get(MasterProduct, product_id)
            store = db.get(Store, offer.store_id)
            alerts.append({
                "shareId": str(share.id),
                "friendName": _display_name(owner),
                "product": _product_payload(db, product),
                "market": {"id": str(store.id), "name": store.name, "chain": store.retailer} if store else None,
                "price": float(offer.price),
                "validUntil": offer.valid_to.isoformat(),
            })
    alerts.sort(key=lambda row: (row["friendName"], row["price"]))
    return alerts


@router.get("/favorites/subscriptions")
def list_friend_favorites(db: Session = Depends(get_db)):
    user = current_user(db, persist=False)
    identity = _linked_identity(db, user)
    if identity is None:
        return {"enabled": False, "friends": [], "alerts": []}
    subscriptions = db.query(FavoriteShareSubscription).filter(FavoriteShareSubscription.subscriber_user_id == user.id).order_by(FavoriteShareSubscription.created_at.asc()).all()
    friends = []
    for sub in subscriptions:
        share = db.get(FavoriteShare, sub.share_id)
        if share is None:
            continue
        ids = _visible_favorite_ids(db, share.owner_user_id) if share.enabled else []
        friends.append({
            "shareId": str(share.id),
            "ownerName": _display_name(share.owner),
            "available": bool(share.enabled),
            "visibleCount": len(ids),
            "items": [_product_payload(db, db.get(MasterProduct, product_id)) for product_id in ids],
            "inAppEnabled": bool(sub.in_app_enabled),
            "pushEnabled": bool(sub.push_enabled),
        })
    enabled_subscriptions = [sub for sub in subscriptions if sub.in_app_enabled]
    return {"enabled": True, "friends": friends, "alerts": _friend_offer_matches(db, user, enabled_subscriptions)}
