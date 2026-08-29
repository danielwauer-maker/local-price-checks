from __future__ import annotations

from datetime import datetime
from urllib.parse import unquote, urlparse, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .account_routes import _linked_profile
from .admin_learning import audit
from .admin_routes import _admin
from .client_context import get_client_key
from .db import get_db
from .models import UserProfile
from .push_models import PushSubscription
from .push_service import send_push_to_user, vapid_public_key

router = APIRouter(tags=["push"])

_TRUSTED_PUSH_HOSTS = {
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
}
_TRUSTED_PUSH_SUFFIXES = (
    ".push.services.mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class PushSubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=8, max_length=4096)
    keys: PushKeys


class PushUnsubscribePayload(BaseModel):
    endpoint: str = Field(min_length=8, max_length=4096)


def _trusted_push_endpoint(endpoint: str) -> bool:
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    if parsed.port not in {None, 443}:
        return False
    return host in _TRUSTED_PUSH_HOSTS or any(host.endswith(suffix) for suffix in _TRUSTED_PUSH_SUFFIXES)


def _safe_internal_target(target: str) -> bool:
    if not target or len(target) > 300 or not target.startswith("/") or target.startswith("//"):
        return False
    if "\\" in target or any(ord(char) < 32 for char in target):
        return False
    try:
        parsed = urlsplit(target)
    except ValueError:
        return False
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return False
    decoded_path = unquote(unquote(parsed.path))
    if "\\" in decoded_path or any(ord(char) < 32 for char in decoded_path):
        return False
    return ".." not in decoded_path.split("/")


def _require_same_origin_admin_post(request: Request) -> None:
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        # Non-browser admin clients cannot be cross-site form submissions.
        if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            raise HTTPException(403, "Admin-Aktion muss von Spareno stammen.")
        return
    try:
        source_host = urlsplit(source).netloc.lower()
    except ValueError as exc:
        raise HTTPException(403, "Ungültige Admin-Anfrage.") from exc
    allowed = {
        request.url.netloc.lower(),
        (request.headers.get("host") or "").lower(),
        (request.headers.get("x-forwarded-host") or "").lower(),
    }
    if not source_host or source_host not in allowed:
        raise HTTPException(403, "Admin-Aktion muss von Spareno stammen.")


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
    if not _trusted_push_endpoint(payload.endpoint):
        raise HTTPException(400, "Ungültiger Web-Push-Endpunkt.")
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
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    _require_same_origin_admin_post(request)
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


@router.post("/admin/users/{user_id}/push-custom")
def admin_push_custom(
    user_id: int,
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    target: str = Form("/"),
    subscription_id: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    _require_same_origin_admin_post(request)
    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(404, "Nutzer nicht gefunden")
    clean_title = title.strip()
    clean_body = body.strip()
    clean_target = target.strip()
    if not 1 <= len(clean_title) <= 80:
        raise HTTPException(400, "Der Push-Titel muss 1 bis 80 Zeichen lang sein.")
    if not 1 <= len(clean_body) <= 300:
        raise HTTPException(400, "Der Push-Text muss 1 bis 300 Zeichen lang sein.")
    if not _safe_internal_target(clean_target):
        raise HTTPException(400, "Das Push-Ziel muss ein sicherer interner Spareno-Pfad sein.")
    try:
        selected_id = int(subscription_id) if subscription_id.strip() else None
    except ValueError as exc:
        raise HTTPException(400, "Ungültiges Push-Gerät.") from exc
    query = db.query(PushSubscription).filter(
        PushSubscription.user_id == user_id,
        PushSubscription.enabled.is_(True),
    )
    if selected_id is not None:
        query = query.filter(PushSubscription.id == selected_id)
    attempted = query.count()
    if selected_id is not None and attempted == 0:
        raise HTTPException(404, "Push-Gerät für diesen Nutzer nicht gefunden.")
    sent = send_push_to_user(
        db,
        user_id,
        title=clean_title,
        body=clean_body,
        url=clean_target,
        tag=f"admin-custom-{user_id}",
        data={"type": "admin_custom"},
        subscription_id=selected_id,
    )
    failed = max(0, attempted - sent)
    audit(
        db,
        "admin_custom_push",
        "user_profile",
        user_id,
        f"target={clean_target}; subscription={selected_id or 'all'}; attempted={attempted}; sent={sent}; failed={failed}",
        actor,
    )
    db.commit()
    return RedirectResponse(
        f"/admin/users?push_user={user_id}&push_sent={sent}&push_failed={failed}&custom_push=1",
        status_code=303,
    )
