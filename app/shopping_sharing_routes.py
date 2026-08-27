from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .client_models import AccountIdentity
from .db import SessionLocal, get_db
from .lokero_models import SharedShoppingList, SharedShoppingListInvite, SharedShoppingListItem, SharedShoppingListMember, SharedShoppingListUserState
from .models import MasterProduct, ProductAdminData, ShoppingItem, UserProfile
from .product_media import preferred_product_media
from .services import current_user

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


def _member(db: Session, list_id: int, user_id: int) -> SharedShoppingListMember | None:
    return (
        db.query(SharedShoppingListMember)
        .filter(SharedShoppingListMember.list_id == list_id, SharedShoppingListMember.user_id == user_id)
        .first()
    )


def _require_member(db: Session, list_id: int, user_id: int) -> tuple[SharedShoppingList, SharedShoppingListMember]:
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
        existing = SharedShoppingList(owner_user_id=user.id, name="Meine Einkaufsliste", is_personal=True, revision=1)
        db.add(existing)
        db.flush()
        db.add(SharedShoppingListMember(list_id=existing.id, user_id=user.id, role="owner"))
        legacy = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
        for row in legacy:
            db.add(SharedShoppingListItem(
                list_id=existing.id,
                master_product_id=row.master_product_id,
                quantity=float(row.quantity),
                checked=False,
                added_by_user_id=user.id,
            ))

    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row is None:
        db.add(SharedShoppingListUserState(user_id=user.id, active_list_id=existing.id))
    db.commit()
    db.refresh(existing)
    return existing


def _memberships(db: Session, user_id: int) -> list[tuple[SharedShoppingListMember, SharedShoppingList]]:
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


def _display_name(user: UserProfile | None) -> str:
    if user is None:
        return "Spareno-Nutzer"
    name = (user.display_name or "").strip()
    if not name or name.lower().startswith("anonym"):
        return "Spareno-Nutzer"
    return name


def _member_payload(db: Session, member: SharedShoppingListMember) -> dict:
    user = db.get(UserProfile, member.user_id)
    identity = db.query(AccountIdentity).filter(AccountIdentity.user_id == member.user_id).order_by(AccountIdentity.id.desc()).first()
    return {
        "userId": str(member.user_id),
        "displayName": _display_name(user),
        "email": identity.email if identity else None,
        "role": member.role,
    }


def _list_summary(db: Session, shopping_list: SharedShoppingList, membership: SharedShoppingListMember) -> dict:
    members = db.query(SharedShoppingListMember).filter(SharedShoppingListMember.list_id == shopping_list.id).order_by(SharedShoppingListMember.joined_at.asc()).all()
    return {
        "id": str(shopping_list.id),
        "name": shopping_list.name,
        "isPersonal": bool(shopping_list.is_personal),
        "role": membership.role,
        "revision": int(shopping_list.revision or 0),
        "memberCount": len(members),
        "members": [_member_payload(db, row) for row in members],
    }


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


def _snapshot(db: Session, shopping_list: SharedShoppingList, membership: SharedShoppingListMember) -> dict:
    rows = db.query(SharedShoppingListItem).filter(SharedShoppingListItem.list_id == shopping_list.id).order_by(SharedShoppingListItem.checked.asc(), SharedShoppingListItem.created_at.asc()).all()
    return {"list": _list_summary(db, shopping_list, membership), "items": [_item_payload(db, row) for row in rows]}


def _mirror_personal_product(db: Session, shopping_list: SharedShoppingList, user_id: int, product_id: int, quantity: float) -> None:
    if not shopping_list.is_personal or shopping_list.owner_user_id != user_id:
        return
    legacy = db.query(ShoppingItem).filter(ShoppingItem.user_id == user_id, ShoppingItem.master_product_id == product_id).first()
    if quantity <= 0:
        if legacy:
            db.delete(legacy)
        return
    if legacy is None:
        db.add(ShoppingItem(user_id=user_id, master_product_id=product_id, quantity=quantity))
    else:
        legacy.quantity = quantity


@router.get("/lists")
def list_shopping_lists(db: Session = Depends(get_db)):
    user = current_user(db, persist=False)
    identity = _linked_identity(db, user)
    if identity is None:
        return {"enabled": False, "reason": "account_required", "activeListId": None, "lists": []}
    personal = _ensure_personal_list(db, user)
    memberships = _memberships(db, user.id)
    state_row = db.get(SharedShoppingListUserState, user.id)
    active_id = state_row.active_list_id if state_row else personal.id
    if not any(row.id == active_id for _, row in memberships):
        active_id = personal.id
    return {
        "enabled": True,
        "activeListId": str(active_id),
        "lists": [_list_summary(db, shopping_list, membership) for membership, shopping_list in memberships],
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
    shopping_list = SharedShoppingList(owner_user_id=user.id, name=" ".join(payload.name.strip().split()), is_personal=False, revision=1)
    db.add(shopping_list)
    db.flush()
    membership = SharedShoppingListMember(list_id=shopping_list.id, user_id=user.id, role="owner")
    db.add(membership)
    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row:
        state_row.active_list_id = shopping_list.id
    else:
        db.add(SharedShoppingListUserState(user_id=user.id, active_list_id=shopping_list.id))
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
def create_list_invite(list_id: int, payload: InvitePayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Nur der Besitzer kann Personen einladen.")
    email = str(payload.email).strip().lower() if payload.email else None
    token = secrets.token_urlsafe(24)
    invite = SharedShoppingListInvite(list_id=shopping_list.id, token=token, invited_email=email, created_by_user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=14))
    db.add(invite)
    db.commit()
    return {"token": token, "listId": str(shopping_list.id), "listName": shopping_list.name, "invitedEmail": email, "expiresAt": invite.expires_at.isoformat()}


@router.get("/lists/invites/{token}")
def inspect_list_invite(token: str, db: Session = Depends(get_db)):
    invite = db.query(SharedShoppingListInvite).filter(SharedShoppingListInvite.token == token).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="Einladung nicht gefunden.")
    shopping_list = db.get(SharedShoppingList, invite.list_id)
    inviter = db.get(UserProfile, invite.created_by_user_id)
    expired = invite.expires_at < datetime.utcnow()
    return {"valid": not expired and invite.accepted_at is None, "listName": shopping_list.name if shopping_list else "Gemeinsame Einkaufsliste", "inviter": _display_name(inviter), "invitedEmail": invite.invited_email, "expiresAt": invite.expires_at.isoformat()}


@router.post("/lists/invites/{token}/accept")
def accept_list_invite(token: str, db: Session = Depends(get_db)):
    user, identity = _require_linked_user(db)
    invite = db.query(SharedShoppingListInvite).filter(SharedShoppingListInvite.token == token).first()
    if invite is None or invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=404, detail="Die Einladung ist abgelaufen oder ungültig.")
    if invite.invited_email and (identity.email or "").strip().lower() != invite.invited_email:
        raise HTTPException(status_code=403, detail="Diese Einladung wurde für eine andere E-Mail-Adresse erstellt.")
    membership = _member(db, invite.list_id, user.id)
    if membership is None:
        membership = SharedShoppingListMember(list_id=invite.list_id, user_id=user.id, role="editor")
        db.add(membership)
    invite.accepted_at = datetime.utcnow()
    invite.accepted_by_user_id = user.id
    state_row = db.get(SharedShoppingListUserState, user.id)
    if state_row is None:
        db.add(SharedShoppingListUserState(user_id=user.id, active_list_id=invite.list_id))
    else:
        state_row.active_list_id = invite.list_id
    shopping_list = db.get(SharedShoppingList, invite.list_id)
    if shopping_list:
        _bump(shopping_list)
    db.commit()
    if shopping_list is None:
        raise HTTPException(status_code=404, detail="Einkaufsliste nicht gefunden.")
    return _snapshot(db, shopping_list, membership)


@router.delete("/lists/{list_id}/members/{member_user_id}")
def remove_list_member(list_id: int, member_user_id: int, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    target = _member(db, list_id, member_user_id)
    if target is None:
        return {"removed": False}
    if member_user_id == shopping_list.owner_user_id:
        raise HTTPException(status_code=400, detail="Der Besitzer kann nicht aus der eigenen Liste entfernt werden.")
    if user.id != member_user_id and membership.role != "owner":
        raise HTTPException(status_code=403, detail="Nur der Besitzer kann andere Mitglieder entfernen.")
    db.delete(target)
    _bump(shopping_list)
    db.commit()
    return {"removed": True}


@router.put("/lists/{list_id}/items/product/{product_id}")
def put_product_item(list_id: int, product_id: int, payload: ProductQuantityPayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    if db.get(MasterProduct, product_id) is None:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden.")
    item = db.query(SharedShoppingListItem).filter(SharedShoppingListItem.list_id == list_id, SharedShoppingListItem.master_product_id == product_id).first()
    quantity = float(payload.quantity)
    if quantity <= 0:
        if item:
            db.delete(item)
            _bump(shopping_list)
        _mirror_personal_product(db, shopping_list, user.id, product_id, 0)
        db.commit()
        return _snapshot(db, shopping_list, membership)
    if item is None:
        item = SharedShoppingListItem(list_id=list_id, master_product_id=product_id, quantity=quantity, checked=False, added_by_user_id=user.id)
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
def add_manual_item(list_id: int, payload: ManualItemPayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    text = " ".join(payload.text.strip().split())
    existing_rows = db.query(SharedShoppingListItem).filter(SharedShoppingListItem.list_id == list_id, SharedShoppingListItem.master_product_id.is_(None)).all()
    item = next((row for row in existing_rows if (row.manual_text or "").casefold() == text.casefold()), None)
    if item:
        item.quantity = float(item.quantity) + float(payload.quantity)
        item.checked = False
        item.checked_by_user_id = None
        item.updated_at = datetime.utcnow()
    else:
        db.add(SharedShoppingListItem(list_id=list_id, manual_text=text, quantity=float(payload.quantity), checked=False, added_by_user_id=user.id))
    _bump(shopping_list)
    db.commit()
    return _snapshot(db, shopping_list, membership)


@router.patch("/lists/{list_id}/items/{item_id}")
def patch_list_item(list_id: int, item_id: int, payload: ItemPatchPayload, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, membership = _require_member(db, list_id, user.id)
    item = db.query(SharedShoppingListItem).filter(SharedShoppingListItem.id == item_id, SharedShoppingListItem.list_id == list_id).first()
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
            _mirror_personal_product(db, shopping_list, user.id, item.master_product_id, float(payload.quantity))
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
    item = db.query(SharedShoppingListItem).filter(SharedShoppingListItem.id == item_id, SharedShoppingListItem.list_id == list_id).first()
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
    items = db.query(SharedShoppingListItem).filter(SharedShoppingListItem.list_id == list_id).all()
    product_ids = [row.master_product_id for row in items if row.master_product_id is not None]
    for row in items:
        db.delete(row)
    if shopping_list.is_personal and shopping_list.owner_user_id == user.id and product_ids:
        db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id, ShoppingItem.master_product_id.in_(product_ids)).delete(synchronize_session=False)
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

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
