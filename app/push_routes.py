from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .account_routes import _linked_profile
from .admin_routes import _admin
from .client_context import get_client_key
from .db import get_db
from .models import UserProfile
from .push_models import PushSubscription
from .push_service import send_push_to_user, vapid_public_key

router = APIRouter(tags=["push"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class PushSubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=8, max_length=4096)
    keys: PushKeys


class PushUnsubscribePayload(BaseModel):
    endpoint: str = Field(min_length=8, max_length=4096)


@router.get("/api/push/config")
def push_config(db: Session = Depends(get_db)):
    profile = _linked_profile(db)
    enabled = False
    if profile is not None:
        client_key = get_client_key()
        query = db.query(PushSubscription).filter(
            PushSubscription.user_id == profile.id,
            PushSubscription.enabled.is_(True),
        )
        if client_key:
            query = query.filter(PushSubscription.client_key == client_key)
        enabled = query.first() is not None
    return {
        "available": True,
        "linked": profile is not None,
        "publicKey": vapid_public_key(),
        "enabledOnThisDevice": enabled,
    }


@router.post("/api/push/subscriptions")
def register_push_subscription(
    payload: PushSubscriptionPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    profile = _linked_profile(db)
    if profile is None:
        raise HTTPException(403, "Für Push-Benachrichtigungen ist ein Spareno-Konto erforderlich.")
    row = db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    if row is None:
        row = PushSubscription(
            user_id=profile.id,
            client_key=get_client_key(),
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=request.headers.get("user-agent"),
            enabled=True,
        )
        db.add(row)
    else:
        row.user_id = profile.id
        row.client_key = get_client_key()
        row.p256dh = payload.keys.p256dh
        row.auth = payload.keys.auth
        row.user_agent = request.headers.get("user-agent")
        row.enabled = True
        row.updated_at = datetime.utcnow()
        row.last_error = None
    db.commit()
    return {"enabled": True}


@router.delete("/api/push/subscriptions")
def remove_push_subscription(payload: PushUnsubscribePayload, db: Session = Depends(get_db)):
    profile = _linked_profile(db)
    if profile is None:
        return {"enabled": False}
    row = db.query(PushSubscription).filter(
        PushSubscription.user_id == profile.id,
        PushSubscription.endpoint == payload.endpoint,
    ).first()
    if row is not None:
        row.enabled = False
        row.updated_at = datetime.utcnow()
        db.commit()
    return {"enabled": False}


@router.post("/admin/users/{user_id}/push-test")
def admin_push_test(
    user_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(404, "Nutzer nicht gefunden")
    sent = send_push_to_user(
        db,
        user_id,
        title="Spareno Test-Benachrichtigung",
        body="Push funktioniert auf diesem Gerät. ✓",
        url="/",
        tag=f"admin-test-{user_id}",
        data={"type": "admin_test", "actor": actor},
    )
    return RedirectResponse(f"/admin/users?push_user={user_id}&push_sent={sent}", status_code=303)
