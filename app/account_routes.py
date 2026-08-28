from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .account_linking import AccountLinkConflict, account_profile_for_client, link_verified_identity
from .account_realtime import publish_account_event, subscribe_account_events
from .client_context import get_client_key
from .client_models import AccountAppPreferences, AccountClientLink, AccountIdentity, UserClient
from .db import get_db
from .models import FavoriteProduct, UserProfile
from .services import current_user
from .supabase_auth import verify_supabase_access_token

router = APIRouter(prefix="/api/account", tags=["account"])

_DEFAULT_NOTIFICATIONS = {
    "priceAlerts": True,
    "newOffers": True,
    "regionAvailable": True,
    "favoriteOffers": False,
}
_DEFAULT_CHAINS = ["REWE", "Lidl", "ALDI SÜD", "Netto", "EDEKA"]


class AccountPreferencesPayload(BaseModel):
    travelCostPerKm: float | None = Field(default=None, ge=0, le=5)
    notifications: dict[str, bool] | None = None
    preferredChains: list[str] | None = None
    diet: list[str] | None = None
    initializeOnly: bool = False


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization fehlt")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Authorization-Header")
    return token.strip()


def _current_client(db: Session) -> UserClient:
    current_user(db)
    key = get_client_key()
    if not key:
        raise HTTPException(status_code=400, detail="Kein Geräte-Client im Request")
    client = db.query(UserClient).filter(UserClient.client_key == key).first()
    if not client:
        raise HTTPException(status_code=400, detail="Geräte-Client konnte nicht aufgelöst werden")
    return client


def _linked_profile(db: Session) -> UserProfile | None:
    key = get_client_key()
    if not key:
        return None
    client = db.query(UserClient).filter(UserClient.client_key == key).first()
    if client is None:
        return None
    return account_profile_for_client(db, client)


def _json_list(raw: str | None, fallback: list[str]) -> list[str]:
    try:
        value = json.loads(raw or "")
        if isinstance(value, list):
            return [str(item) for item in value]
    except (TypeError, ValueError):
        pass
    return list(fallback)


def _json_notifications(raw: str | None) -> dict[str, bool]:
    result = dict(_DEFAULT_NOTIFICATIONS)
    try:
        value = json.loads(raw or "")
        if isinstance(value, dict):
            for key in result:
                if key in value:
                    result[key] = bool(value[key])
    except (TypeError, ValueError):
        pass
    return result


def _preferences_payload(row: AccountAppPreferences | None) -> dict:
    if row is None:
        return {
            "travelCostPerKm": 0.3,
            "notifications": dict(_DEFAULT_NOTIFICATIONS),
            "preferredChains": list(_DEFAULT_CHAINS),
            "diet": [],
        }
    return {
        "travelCostPerKm": float(row.travel_cost_per_km),
        "notifications": _json_notifications(row.notifications_json),
        "preferredChains": _json_list(row.preferred_chains_json, _DEFAULT_CHAINS),
        "diet": _json_list(row.diet_json, []),
    }


def _account_state_payload(db: Session, profile: UserProfile) -> dict:
    prefs = db.query(AccountAppPreferences).filter(AccountAppPreferences.user_id == profile.id).first()
    favorite_ids = [
        str(row.master_product_id)
        for row in db.query(FavoriteProduct)
        .filter(FavoriteProduct.user_id == profile.id)
        .order_by(FavoriteProduct.master_product_id.asc())
        .all()
    ]
    return {
        "linked": True,
        "profileId": profile.id,
        "favoriteProductIds": favorite_ids,
        "preferencesInitialized": prefs is not None,
        "preferences": _preferences_payload(prefs),
    }


@router.post("/link")
def link_account(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    verified = verify_supabase_access_token(_bearer_token(authorization))
    client = _current_client(db)
    try:
        profile = link_verified_identity(
            db,
            client=client,
            provider="supabase",
            provider_subject=verified.user_id,
            email=verified.email,
        )
    except AccountLinkConflict as exc:
        raise HTTPException(status_code=409, detail="Dieses Gerät ist bereits mit einem anderen Konto verknüpft.") from exc
    publish_account_event(profile.id, "state")
    return {"linked": True, "profileId": profile.id, "email": verified.email}


@router.get("/status")
def account_status(db: Session = Depends(get_db)):
    key = get_client_key()
    if not key:
        return {"linked": False}
    client = db.query(UserClient).filter(UserClient.client_key == key).first()
    if not client:
        return {"linked": False}
    profile = account_profile_for_client(db, client)
    if profile is None:
        return {"linked": False, "profileId": client.user_id}
    identity = (
        db.query(AccountIdentity)
        .join(AccountClientLink, AccountClientLink.identity_id == AccountIdentity.id)
        .filter(AccountClientLink.client_id == client.id)
        .first()
    )
    return {"linked": True, "profileId": profile.id, "email": identity.email if identity else None}


@router.get("/state")
def account_state(db: Session = Depends(get_db)):
    profile = _linked_profile(db)
    if profile is None:
        return {"linked": False}
    return _account_state_payload(db, profile)


@router.get("/events")
async def account_events(request: Request, db: Session = Depends(get_db)):
    profile = _linked_profile(db)
    if profile is None:
        raise HTTPException(status_code=403, detail="Für Realtime-Synchronisierung ist ein Spareno-Account erforderlich.")
    user_id = int(profile.id)
    queue, unsubscribe = subscribe_account_events(user_id)

    async def stream():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: {event.kind}\ndata: {{}}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.put("/preferences")
def update_account_preferences(payload: AccountPreferencesPayload, db: Session = Depends(get_db)):
    profile = _linked_profile(db)
    if profile is None:
        raise HTTPException(status_code=403, detail="Für die Synchronisierung ist ein Spareno-Account erforderlich.")

    row = db.query(AccountAppPreferences).filter(AccountAppPreferences.user_id == profile.id).first()
    if row is not None and payload.initializeOnly:
        return _account_state_payload(db, profile)

    if row is None:
        row = AccountAppPreferences(user_id=profile.id)
        db.add(row)
        db.flush()

    if payload.travelCostPerKm is not None:
        row.travel_cost_per_km = float(payload.travelCostPerKm)
    if payload.notifications is not None:
        notifications = _json_notifications(row.notifications_json)
        for key in notifications:
            if key in payload.notifications:
                notifications[key] = bool(payload.notifications[key])
        row.notifications_json = json.dumps(notifications, separators=(",", ":"), ensure_ascii=False)
    if payload.preferredChains is not None:
        row.preferred_chains_json = json.dumps([str(item) for item in payload.preferredChains], separators=(",", ":"), ensure_ascii=False)
    if payload.diet is not None:
        row.diet_json = json.dumps([str(item) for item in payload.diet], separators=(",", ":"), ensure_ascii=False)
    row.updated_at = datetime.utcnow()
    db.commit()
    publish_account_event(profile.id, "state")
    return _account_state_payload(db, profile)
