from __future__ import annotations

import asyncio
import io
import json
import secrets
from datetime import datetime, timedelta
from typing import Iterable

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .client_models import AccountIdentity
from .clock import app_today
from .db import SessionLocal, get_db
from .models import FavoriteProduct, MasterProduct, Offer, ProductAdminData, ShoppingItem, Store, UserProfile
from .product_media import preferred_product_media
from .services import current_user, selected_store_ids
from .sharing_models import (
    FavoriteShare,
    FavoriteShareItemVisibility,
    FavoriteShareSubscription,
    SharedShoppingList,
    SharedShoppingListInvite,
    SharedShoppingListItem,
    SharedShoppingListMember,
    SharedShoppingListUserState,
)

router = APIRouter(prefix="/api/sharing", tags=["sharing"])


class CreateListPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InvitePayload(BaseModel):
    email: EmailStr | None = None


class ProductQuantityPayload(BaseModel):
    quantity: float = Field(ge=0, le=999)


class ManualItemPayload(BaseModel):
    text: str = Field(min_length=1, max_length=120)
    quantity: float = Field(default=1, gt=0, le=999)


class ItemPatchPayload(BaseModel):
    quantity: float | None = Field(default=None, ge=0, le=999)
    checked: bool | None = None


class ShareEnabledPayload(BaseModel):
    enabled: bool


class FavoriteVisibilityPayload(BaseModel):
    visible: bool


class SubscriptionSettingsPayload(BaseModel):
    inAppEnabled: bool | None = None
    pushEnabled: bool | None = None


def _linked_identity(db: Session, user: UserProfile) -> AccountIdentity | None:
    if user.id is None:
        return None
    return (
        db.query(AccountIdentity)
        .filter(AccountIdentity.user_id == user.id)
        .order_by(AccountIdentity.last_seen_at.desc(), AccountIdentity.id.desc())
        .first()
    )


def _require_linked_user(db: Session) -> tuple[UserProfile, AccountIdentity]:
    user = current_user(db, persist=False)
    identity = _linked_identity(db, user)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Für diese Funktion ist ein verknüpfter Spareno-Account erforderlich.",
        )
    return user, identity


def _display_name(user: UserProfile | None) -> str:
    if user is None:
        return "Spareno-Nutzer"
    name = (user.display_name or "").strip()
    if not name or name.lower().startswith("anonym"):
        return "Spareno-Nutzer"
    return name


def _product_payload(db: Session, product: MasterProduct | None) -> dict | None:
    if product is None:
        return None
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product.id).first()
    category = meta.category.name if meta and meta.category else "Sonstiges"
    media = preferred_product_media(db, product.id, purpose="public")
    image_url = None
    if media is not None:
        image_url = f"/media/{media.file_path}" if media.file_path else media.source_url
    return {
        "id": str(product.id),
        "name": product.name,
        "brand": product.brand or "",
        "amount": product.package_size or "",
        "category": category,
        "imageUrl": image_url,
    }


# ---------------------------------------------------------------------------
# Shared shopping lists
# ---------------------------------------------------------------------------


def _member(db: Session, list_id: int, user_id: int) -> SharedShoppingListMember | None:
    return (
        db.query(SharedShoppingListMember)
        .filter(
            SharedShoppingListMember.list_id == list_id,
            SharedShoppingListMember.user_id == user_id,
        )
        .first()
    )


def _require_member(
    db: Session, list_id: int, user_id: int
) -> tuple[SharedShoppingList, SharedShoppingListMember]:
    shopping_list = db.get(SharedShoppingList, list_id)
    membership = _member(db, list_id, user_id)
    if shopping_list is None or membership is None:
        raise HTTPException(status_code=404, detail="Einkaufsliste nicht gefunden.")
    return shopping_list, membership


def _bump(shopping_list: SharedShoppingList) -> None:
    shopping_list.revision = int(shopping_list.revision or 0) + 1
    shopping_list.updated_at = datetime.utcnow()


def _ensure_personal_list(db: Session, user: UserProfile) -> SharedShoppingList:
    existing = (
        db.query(SharedShoppingList)
        .join(SharedShoppingListMember, SharedShoppingListMember.list_id == SharedShoppingList.id)
        .filter(
            SharedShoppingListMember.user_id == user.id,
            SharedShoppingList.owner_user_id == user.id,
            SharedShoppingList.is_personal.is_(True),
        )
        .order_by(SharedShoppingList.id)
        .first()
    )
    if existing is None:
        existing = SharedShoppingList(
            owner_user_id=user.id,
            name="Meine Einkaufsliste",
            is_personal=True,
            revision=1,
        )
        db.add(existing)
        db.flush()
        db.add(SharedShoppingListMember(list_id=existing.id, user_id=user.id, role="owner"))

        # One-time compatibility import from the current personal basket.
        for row in db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all():
            db.add(
                SharedShoppingListItem(
                    list_id=existing.id,
                    master_product_id=row.master_product_id,
                    quantity=float(row.quantity),
                    checked=False,
                    added_by_user_id=user.id,
                )
            )

    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row is None:
        db.add(SharedShoppingListUserState(user_id=user.id, active_list_id=existing.id))
    db.commit()
    db.refresh(existing)
    return existing


def _memberships(
    db: Session, user_id: int
) -> list[tuple[SharedShoppingListMember, SharedShoppingList]]:
    return (
        db.query(SharedShoppingListMember, SharedShoppingList)
        .join(SharedShoppingList, SharedShoppingList.id == SharedShoppingListMember.list_id)
        .filter(SharedShoppingListMember.user_id == user_id)
        .order_by(SharedShoppingList.is_personal.desc(), SharedShoppingList.created_at.asc())
        .all()
    )


def _active_list(db: Session, user: UserProfile) -> SharedShoppingList:
    personal = _ensure_personal_list(db, user)
    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row:
        active = db.get(SharedShoppingList, state_row.active_list_id)
        if active and _member(db, active.id, user.id):
            return active
        state_row.active_list_id = personal.id
    else:
        db.add(SharedShoppingListUserState(user_id=user.id, active_list_id=personal.id))
    db.commit()
    return personal


def _member_payload(db: Session, member: SharedShoppingListMember) -> dict:
    user = db.get(UserProfile, member.user_id)
    identity = (
        db.query(AccountIdentity)
        .filter(AccountIdentity.user_id == member.user_id)
        .order_by(AccountIdentity.id.desc())
        .first()
    )
    return {
        "userId": str(member.user_id),
        "displayName": _display_name(user),
        "email": identity.email if identity else None,
        "role": member.role,
    }


def _list_summary(
    db: Session, shopping_list: SharedShoppingList, membership: SharedShoppingListMember
) -> dict:
    members = (
        db.query(SharedShoppingListMember)
        .filter(SharedShoppingListMember.list_id == shopping_list.id)
        .order_by(SharedShoppingListMember.joined_at.asc())
        .all()
    )
    return {
        "id": str(shopping_list.id),
        "name": shopping_list.name,
        "isPersonal": bool(shopping_list.is_personal),
        "role": membership.role,
        "revision": int(shopping_list.revision or 0),
        "memberCount": len(members),
        "members": [_member_payload(db, row) for row in members],
    }


def _item_payload(db: Session, item: SharedShoppingListItem) -> dict:
    return {
        "id": str(item.id),
        "productId": str(item.master_product_id) if item.master_product_id is not None else None,
        "manualText": item.manual_text,
        "quantity": float(item.quantity),
        "checked": bool(item.checked),
        "addedBy": _display_name(item.added_by),
        "checkedBy": _display_name(item.checked_by) if item.checked_by_user_id else None,
        "product": _product_payload(db, item.product),
    }


def _snapshot(
    db: Session, shopping_list: SharedShoppingList, membership: SharedShoppingListMember
) -> dict:
    rows = (
        db.query(SharedShoppingListItem)
        .filter(SharedShoppingListItem.list_id == shopping_list.id)
        .order_by(SharedShoppingListItem.checked.asc(), SharedShoppingListItem.created_at.asc())
        .all()
    )
    return {
        "list": _list_summary(db, shopping_list, membership),
        "items": [_item_payload(db, row) for row in rows],
    }


def _mirror_personal_product(
    db: Session,
    shopping_list: SharedShoppingList,
    actor_user_id: int,
    product_id: int,
    quantity: float,
) -> None:
    # Legacy optimizer remains correct only for the owner's personal list.
    if not shopping_list.is_personal or shopping_list.owner_user_id != actor_user_id:
        return
    legacy = (
        db.query(ShoppingItem)
        .filter(
            ShoppingItem.user_id == actor_user_id,
            ShoppingItem.master_product_id == product_id,
        )
        .first()
    )
    if quantity <= 0:
        if legacy:
            db.delete(legacy)
        return
    if legacy is None:
        db.add(
            ShoppingItem(
                user_id=actor_user_id,
                master_product_id=product_id,
                quantity=quantity,
            )
        )
    else:
        legacy.quantity = quantity


@router.get("/lists")
def list_shopping_lists(db: Session = Depends(get_db)):
    user = current_user(db, persist=False)
    identity = _linked_identity(db, user)
    if identity is None:
        return {
            "enabled": False,
            "reason": "account_required",
            "activeListId": None,
            "lists": [],
        }
    personal = _ensure_personal_list(db, user)
    memberships = _memberships(db, user.id)
    state_row = db.get(SharedShoppingListUserState, user.id)
    active_id = state_row.active_list_id if state_row else personal.id
    if not any(row.id == active_id for _, row in memberships):
        active_id = personal.id
        if state_row:
            state_row.active_list_id = personal.id
            db.commit()
    return {
        "enabled": True,
        "activeListId": str(active_id),
        "lists": [
            _list_summary(db, shopping_list, membership)
            for membership, shopping_list in memberships
        ],
    }


@router.get("/lists/active")
def get_active_shopping_list(db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list = _active_list(db, user)
    membership = _member(db, shopping_list.id, user.id)
    assert membership is not None
    return _snapshot(db, shopping_list, membership)


@router.post("/lists")
def create_shopping_list(payload: CreateListPayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    _ensure_personal_list(db, user)
    name = " ".join(payload.name.strip().split())
    shopping_list = SharedShoppingList(
        owner_user_id=user.id,
        name=name,
        is_personal=False,
        revision=1,
    )
    db.add(shopping_list)
    db.flush()
    membership = SharedShoppingListMember(
        list_id=shopping_list.id,
        user_id=user.id,
        role="owner",
    )
    db.add(membership)
    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row:
        state_row.active_list_id = shopping_list.id
    else:
        db.add(
            SharedShoppingListUserState(
                user_id=user.id,
                active_list_id=shopping_list.id,
            )
        )
    db.commit()
    db.refresh(shopping_list)
    return _list_summary(db, shopping_list, membership)


@router.put("/lists/{list_id}/active")
def set_active_shopping_list(list_id: int, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row is None:
        db.add(SharedShoppingListUserState(user_id=user.id, active_list_id=shopping_list.id))
    else:
        state_row.active_list_id = shopping_list.id
    db.commit()
    return _snapshot(db, shopping_list, membership)


@router.post("/lists/{list_id}/invite")
def create_list_invite(
    list_id: int, payload: InvitePayload, db: Session = Depends(get_db)
):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Nur der Besitzer kann Personen einladen.")
    email = str(payload.email).strip().lower() if payload.email else None
    invite = SharedShoppingListInvite(
        list_id=shopping_list.id,
        token=secrets.token_urlsafe(24),
        invited_email=email,
        created_by_user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=14),
    )
    db.add(invite)
    db.commit()
    return {
        "token": invite.token,
        "listId": str(shopping_list.id),
        "listName": shopping_list.name,
        "invitedEmail": email,
        "expiresAt": invite.expires_at.isoformat(),
    }


@router.get("/lists/invites/{token}")
def inspect_list_invite(token: str, db: Session = Depends(get_db)):
    invite = (
        db.query(SharedShoppingListInvite)
        .filter(SharedShoppingListInvite.token == token)
        .first()
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="Einladung nicht gefunden.")
    shopping_list = db.get(SharedShoppingList, invite.list_id)
    inviter = db.get(UserProfile, invite.created_by_user_id)
    expired = invite.expires_at < datetime.utcnow()
    return {
        "valid": not expired and invite.accepted_at is None,
        "listName": shopping_list.name if shopping_list else "Gemeinsame Einkaufsliste",
        "inviter": _display_name(inviter),
        "invitedEmail": invite.invited_email,
        "expiresAt": invite.expires_at.isoformat(),
    }


@router.post("/lists/invites/{token}/accept")
def accept_list_invite(token: str, db: Session = Depends(get_db)):
    user, identity = _require_linked_user(db)
    invite = (
        db.query(SharedShoppingListInvite)
        .filter(SharedShoppingListInvite.token == token)
        .first()
    )
    if invite is None or invite.expires_at < datetime.utcnow() or invite.accepted_at is not None:
        raise HTTPException(status_code=404, detail="Die Einladung ist abgelaufen oder ungültig.")
    if invite.invited_email and (identity.email or "").strip().lower() != invite.invited_email:
        raise HTTPException(
            status_code=403,
            detail="Diese Einladung wurde für eine andere E-Mail-Adresse erstellt.",
        )
    membership = _member(db, invite.list_id, user.id)
    if membership is None:
        membership = SharedShoppingListMember(
            list_id=invite.list_id,
            user_id=user.id,
            role="editor",
        )
        db.add(membership)
    invite.accepted_at = datetime.utcnow()
    invite.accepted_by_user_id = user.id
    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row is None:
        db.add(SharedShoppingListUserState(user_id=user.id, active_list_id=invite.list_id))
    else:
        state_row.active_list_id = invite.list_id
    shopping_list = db.get(SharedShoppingList, invite.list_id)
    if shopping_list is None:
        raise HTTPException(status_code=404, detail="Einkaufsliste nicht gefunden.")
    _bump(shopping_list)
    db.commit()
    return _snapshot(db, shopping_list, membership)


@router.delete("/lists/{list_id}/members/{member_user_id}")
def remove_list_member(list_id: int, member_user_id: int, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    target = _member(db, list_id, member_user_id)
    if target is None:
        return {"removed": False}
    if member_user_id == shopping_list.owner_user_id:
        raise HTTPException(status_code=400, detail="Der Besitzer kann nicht entfernt werden.")
    if user.id != member_user_id and membership.role != "owner":
        raise HTTPException(status_code=403, detail="Nur der Besitzer kann andere Mitglieder entfernen.")
    target_user = db.get(UserProfile, target.user_id)
    db.delete(target)
    target_state = db.get(SharedShoppingListUserState, member_user_id)
    if target_state and target_state.active_list_id == list_id and target_user is not None:
        target_state.active_list_id = _ensure_personal_list(db, target_user).id
    _bump(shopping_list)
    db.commit()
    return {"removed": True}


@router.put("/lists/{list_id}/items/product/{product_id}")
def put_product_item(
    list_id: int,
    product_id: int,
    payload: ProductQuantityPayload,
    db: Session = Depends(get_db),
):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    if db.get(MasterProduct, product_id) is None:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden.")
    item = (
        db.query(SharedShoppingListItem)
        .filter(
            SharedShoppingListItem.list_id == list_id,
            SharedShoppingListItem.master_product_id == product_id,
        )
        .first()
    )
    quantity = float(payload.quantity)
    if quantity <= 0:
        if item:
            db.delete(item)
            _bump(shopping_list)
        _mirror_personal_product(db, shopping_list, user.id, product_id, 0)
        db.commit()
        return _snapshot(db, shopping_list, membership)
    if item is None:
        item = SharedShoppingListItem(
            list_id=list_id,
            master_product_id=product_id,
            quantity=quantity,
            checked=False,
            added_by_user_id=user.id,
        )
        db.add(item)
    else:
        item.quantity = quantity
        item.checked = False
        item.checked_by_user_id = None
        item.updated_at = datetime.utcnow()
    _mirror_personal_product(db, shopping_list, user.id, product_id, quantity)
    _bump(shopping_list)
    db.commit()
    return _snapshot(db, shopping_list, membership)


@router.post("/lists/{list_id}/items/manual")
def add_manual_item(
    list_id: int,
    payload: ManualItemPayload,
    db: Session = Depends(get_db),
):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    text = " ".join(payload.text.strip().split())
    rows = (
        db.query(SharedShoppingListItem)
        .filter(
            SharedShoppingListItem.list_id == list_id,
            SharedShoppingListItem.master_product_id.is_(None),
        )
        .all()
    )
    item = next(
        (row for row in rows if (row.manual_text or "").casefold() == text.casefold()),
        None,
    )
    if item:
        item.quantity = float(item.quantity) + float(payload.quantity)
        item.checked = False
        item.checked_by_user_id = None
        item.updated_at = datetime.utcnow()
    else:
        db.add(
            SharedShoppingListItem(
                list_id=list_id,
                manual_text=text,
                quantity=float(payload.quantity),
                checked=False,
                added_by_user_id=user.id,
            )
        )
    _bump(shopping_list)
    db.commit()
    return _snapshot(db, shopping_list, membership)


@router.patch("/lists/{list_id}/items/{item_id}")
def patch_list_item(
    list_id: int,
    item_id: int,
    payload: ItemPatchPayload,
    db: Session = Depends(get_db),
):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    item = (
        db.query(SharedShoppingListItem)
        .filter(
            SharedShoppingListItem.id == item_id,
            SharedShoppingListItem.list_id == list_id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Listeneintrag nicht gefunden.")
    if payload.quantity is not None:
        if payload.quantity <= 0:
            product_id = item.master_product_id
            db.delete(item)
            if product_id is not None:
                _mirror_personal_product(db, shopping_list, user.id, product_id, 0)
            _bump(shopping_list)
            db.commit()
            return _snapshot(db, shopping_list, membership)
        item.quantity = float(payload.quantity)
        if item.master_product_id is not None:
            _mirror_personal_product(
                db,
                shopping_list,
                user.id,
                item.master_product_id,
                float(payload.quantity),
            )
    if payload.checked is not None:
        item.checked = bool(payload.checked)
        item.checked_by_user_id = user.id if item.checked else None
    item.updated_at = datetime.utcnow()
    _bump(shopping_list)
    db.commit()
    return _snapshot(db, shopping_list, membership)


@router.delete("/lists/{list_id}/items/{item_id}")
def delete_list_item(list_id: int, item_id: int, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    item = (
        db.query(SharedShoppingListItem)
        .filter(
            SharedShoppingListItem.id == item_id,
            SharedShoppingListItem.list_id == list_id,
        )
        .first()
    )
    if item:
        product_id = item.master_product_id
        db.delete(item)
        if product_id is not None:
            _mirror_personal_product(db, shopping_list, user.id, product_id, 0)
        _bump(shopping_list)
        db.commit()
    return _snapshot(db, shopping_list, membership)


@router.delete("/lists/{list_id}/items")
def clear_list_items(list_id: int, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    items = (
        db.query(SharedShoppingListItem)
        .filter(SharedShoppingListItem.list_id == list_id)
        .all()
    )
    product_ids = [row.master_product_id for row in items if row.master_product_id is not None]
    for row in items:
        db.delete(row)
    if shopping_list.is_personal and shopping_list.owner_user_id == user.id and product_ids:
        db.query(ShoppingItem).filter(
            ShoppingItem.user_id == user.id,
            ShoppingItem.master_product_id.in_(product_ids),
        ).delete(synchronize_session=False)
    _bump(shopping_list)
    db.commit()
    return _snapshot(db, shopping_list, membership)


@router.get("/lists/{list_id}/events")
async def list_events(list_id: int, request: Request, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    _require_member(db, list_id, user.id)
    user_id = int(user.id)

    async def stream():
        last_revision: int | None = None
        heartbeat = 0
        while True:
            if await request.is_disconnected():
                break
            session = SessionLocal()
            try:
                if _member(session, list_id, user_id) is None:
                    yield "event: access_revoked\ndata: {}\n\n"
                    break
                shopping_list = session.get(SharedShoppingList, list_id)
                if shopping_list is None:
                    yield "event: removed\ndata: {}\n\n"
                    break
                revision = int(shopping_list.revision or 0)
                if last_revision is None or revision != last_revision:
                    last_revision = revision
                    yield f"event: revision\ndata: {json.dumps({'revision': revision})}\n\n"
                heartbeat += 1
                if heartbeat >= 15:
                    heartbeat = 0
                    yield ": keep-alive\n\n"
            finally:
                session.close()
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Favorite sharing
# ---------------------------------------------------------------------------


def _get_or_create_share(db: Session, user_id: int) -> FavoriteShare:
    row = db.query(FavoriteShare).filter(FavoriteShare.owner_user_id == user_id).first()
    if row is None:
        row = FavoriteShare(
            owner_user_id=user_id,
            token=secrets.token_urlsafe(24),
            enabled=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _favorite_visibility_map(db: Session, user_id: int) -> dict[int, bool]:
    rows = (
        db.query(FavoriteShareItemVisibility)
        .filter(FavoriteShareItemVisibility.owner_user_id == user_id)
        .all()
    )
    return {row.master_product_id: bool(row.visible) for row in rows}


def _visible_favorite_ids(db: Session, owner_user_id: int) -> list[int]:
    visibility = _favorite_visibility_map(db, owner_user_id)
    rows = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == owner_user_id).all()
    return [
        row.master_product_id
        for row in rows
        if visibility.get(row.master_product_id, True)
    ]


def _share_payload(db: Session, share: FavoriteShare, *, include_token: bool) -> dict:
    owner = db.get(UserProfile, share.owner_user_id)
    favorite_rows = (
        db.query(FavoriteProduct)
        .filter(FavoriteProduct.user_id == share.owner_user_id)
        .all()
    )
    visibility = _favorite_visibility_map(db, share.owner_user_id)
    payload = {
        "enabled": bool(share.enabled),
        "ownerName": _display_name(owner),
        "visibleCount": sum(
            1 for row in favorite_rows if visibility.get(row.master_product_id, True)
        ),
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
    return {
        "enabledForAccount": True,
        "share": _share_payload(db, share, include_token=True) if share else None,
    }


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
def set_favorite_visibility(
    product_id: int,
    payload: FavoriteVisibilityPayload,
    db: Session = Depends(get_db),
):
    user, _ = _require_linked_user(db)
    favorite = (
        db.query(FavoriteProduct)
        .filter(
            FavoriteProduct.user_id == user.id,
            FavoriteProduct.master_product_id == product_id,
        )
        .first()
    )
    if favorite is None:
        raise HTTPException(status_code=404, detail="Produkt ist kein Favorit.")
    row = (
        db.query(FavoriteShareItemVisibility)
        .filter(
            FavoriteShareItemVisibility.owner_user_id == user.id,
            FavoriteShareItemVisibility.master_product_id == product_id,
        )
        .first()
    )
    if row is None:
        row = FavoriteShareItemVisibility(
            owner_user_id=user.id,
            master_product_id=product_id,
            visible=payload.visible,
        )
        db.add(row)
    else:
        row.visible = payload.visible
        row.updated_at = datetime.utcnow()
    db.commit()
    share = db.query(FavoriteShare).filter(FavoriteShare.owner_user_id == user.id).first()
    return {
        "visible": payload.visible,
        "share": _share_payload(db, share, include_token=True) if share else None,
    }


@router.get("/favorites/public/{token}")
def public_favorites(token: str, db: Session = Depends(get_db)):
    share = db.query(FavoriteShare).filter(FavoriteShare.token == token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    owner = db.get(UserProfile, share.owner_user_id)
    if not share.enabled:
        return {"available": False, "ownerName": _display_name(owner), "items": []}
    products = [
        db.get(MasterProduct, product_id)
        for product_id in _visible_favorite_ids(db, share.owner_user_id)
    ]
    return {
        "available": True,
        "ownerName": _display_name(owner),
        "items": [_product_payload(db, product) for product in products if product is not None],
    }


@router.get("/favorites/public/{token}/qr.svg")
def favorite_share_qr(token: str, request: Request, db: Session = Depends(get_db)):
    share = db.query(FavoriteShare).filter(FavoriteShare.token == token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    public_url = f"{str(request.base_url).rstrip('/')}/favoriten/geteilt/{share.token}"
    image = qrcode.make(
        public_url,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=8,
        border=2,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/favorites/subscriptions/{token}")
def subscribe_favorites(token: str, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    share = db.query(FavoriteShare).filter(FavoriteShare.token == token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden.")
    if share.owner_user_id == user.id:
        raise HTTPException(
            status_code=400,
            detail="Die eigenen Favoriten können nicht als Freund gespeichert werden.",
        )
    row = (
        db.query(FavoriteShareSubscription)
        .filter(
            FavoriteShareSubscription.subscriber_user_id == user.id,
            FavoriteShareSubscription.share_id == share.id,
        )
        .first()
    )
    if row is None:
        db.add(
            FavoriteShareSubscription(
                subscriber_user_id=user.id,
                share_id=share.id,
                in_app_enabled=True,
                push_enabled=False,
            )
        )
        db.commit()
    return {"subscribed": True}


@router.delete("/favorites/subscriptions/{share_id}")
def unsubscribe_favorites(share_id: int, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    row = (
        db.query(FavoriteShareSubscription)
        .filter(
            FavoriteShareSubscription.subscriber_user_id == user.id,
            FavoriteShareSubscription.share_id == share_id,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return {"subscribed": False}


@router.patch("/favorites/subscriptions/{share_id}")
def update_subscription(
    share_id: int,
    payload: SubscriptionSettingsPayload,
    db: Session = Depends(get_db),
):
    user, _ = _require_linked_user(db)
    row = (
        db.query(FavoriteShareSubscription)
        .filter(
            FavoriteShareSubscription.subscriber_user_id == user.id,
            FavoriteShareSubscription.share_id == share_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Freundesfavoriten nicht gespeichert.")
    if payload.inAppEnabled is not None:
        row.in_app_enabled = payload.inAppEnabled
    if payload.pushEnabled is not None:
        row.push_enabled = payload.pushEnabled
    db.commit()
    return {
        "inAppEnabled": row.in_app_enabled,
        "pushEnabled": row.push_enabled,
    }


def _friend_offer_matches(
    db: Session,
    subscriber: UserProfile,
    subscriptions: Iterable[FavoriteShareSubscription],
) -> list[dict]:
    selected_ids = selected_store_ids(db, subscriber)
    if not selected_ids:
        return []
    today = app_today()
    current_offers = (
        db.query(Offer)
        .filter(
            Offer.store_id.in_(selected_ids),
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= today,
            Offer.valid_to >= today,
        )
        .all()
    )
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
        owner = db.get(UserProfile, share.owner_user_id)
        for product_id in _visible_favorite_ids(db, share.owner_user_id):
            offer = by_product.get(product_id)
            if offer is None:
                continue
            product = db.get(MasterProduct, product_id)
            store = db.get(Store, offer.store_id)
            alerts.append(
                {
                    "shareId": str(share.id),
                    "friendName": _display_name(owner),
                    "product": _product_payload(db, product),
                    "market": {
                        "id": str(store.id),
                        "name": store.name,
                        "chain": store.retailer,
                    }
                    if store
                    else None,
                    "price": float(offer.price),
                    "validUntil": offer.valid_to.isoformat(),
                }
            )
    alerts.sort(key=lambda row: (row["friendName"], row["price"]))
    return alerts


@router.get("/favorites/subscriptions")
def list_friend_favorites(db: Session = Depends(get_db)):
    user = current_user(db, persist=False)
    identity = _linked_identity(db, user)
    if identity is None:
        return {"enabled": False, "friends": [], "alerts": []}
    subscriptions = (
        db.query(FavoriteShareSubscription)
        .filter(FavoriteShareSubscription.subscriber_user_id == user.id)
        .order_by(FavoriteShareSubscription.created_at.asc())
        .all()
    )
    friends = []
    for sub in subscriptions:
        share = db.get(FavoriteShare, sub.share_id)
        if share is None:
            continue
        owner = db.get(UserProfile, share.owner_user_id)
        ids = _visible_favorite_ids(db, share.owner_user_id) if share.enabled else []
        friends.append(
            {
                "shareId": str(share.id),
                "ownerName": _display_name(owner),
                "available": bool(share.enabled),
                "visibleCount": len(ids),
                "items": [
                    _product_payload(db, db.get(MasterProduct, product_id))
                    for product_id in ids
                ],
                "inAppEnabled": bool(sub.in_app_enabled),
                "pushEnabled": bool(sub.push_enabled),
            }
        )
    enabled_subscriptions = [sub for sub in subscriptions if sub.in_app_enabled]
    return {
        "enabled": True,
        "friends": friends,
        "alerts": _friend_offer_matches(db, user, enabled_subscriptions),
    }
