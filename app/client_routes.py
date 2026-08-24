from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .client_context import get_client_key
from .client_models import ClientAppRating, ClientDevice, ClientPricingFeedback, UserClient
from .db import get_db
from .device_detection import detect_device
from .services import current_user

router = APIRouter(prefix="/api/client")


class ClientHeartbeat(BaseModel):
    pwaInstalled: bool = False
    standalone: bool = False
    platform: str = ""
    mobile: bool = False
    touchPoints: int = Field(default=0, ge=0, le=20)
    screenWidth: int | None = Field(default=None, ge=1, le=20000)
    screenHeight: int | None = Field(default=None, ge=1, le=20000)
    pixelRatio: float | None = Field(default=None, ge=0.5, le=10)


class PricingFeedbackPayload(BaseModel):
    savingsValue: Literal["significant", "some", "not_yet", "unsure"]
    monthlyPrice: Literal["1.99", "2.99", "4.99", "9.99", "none"]
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/heartbeat")
def client_heartbeat(payload: ClientHeartbeat, request: Request, db: Session = Depends(get_db)):
    """Record device metadata only for an already materialized client.

    Heartbeats are technical telemetry and must never create a durable user by
    themselves. A visitor becomes a persisted user only after a real personal
    action such as profile/location state, favorites, shopping state, feedback
    or account registration.
    """
    user = current_user(db, persist=False)
    client_key = get_client_key()
    client = db.query(UserClient).filter(UserClient.client_key == client_key).first() if client_key else None
    if not client:
        return {"ok": True, "userId": None, "pwaInstalled": False, "materialized": False}

    now = datetime.utcnow()
    user_agent = (request.headers.get("user-agent") or "")[:1000]
    platform = (payload.platform or "")[:80]
    detected = detect_device(
        user_agent,
        mobile_hint=payload.mobile,
        platform=platform,
        touch_points=payload.touchPoints,
    )

    client.last_seen_at = now
    if payload.pwaInstalled or payload.standalone:
        client.pwa_installed = True
        client.pwa_last_seen_at = now
    client.platform = platform or client.platform
    client.user_agent = user_agent or client.user_agent

    device = db.query(ClientDevice).filter(ClientDevice.client_id == client.id).first()
    if device is None:
        device = ClientDevice(client_id=client.id, device_key=client.client_key, first_seen_at=now)
        db.add(device)

    device.device_key = client.client_key
    device.device_type = detected.device_type
    device.os_name = detected.os_name
    device.os_version = detected.os_version
    device.browser_name = detected.browser_name
    device.browser_version = detected.browser_version
    device.platform = platform or None
    device.mobile_hint = payload.mobile
    device.touch_points = payload.touchPoints
    device.screen_width = payload.screenWidth
    device.screen_height = payload.screenHeight
    device.pixel_ratio = payload.pixelRatio
    device.standalone = payload.standalone or payload.pwaInstalled
    device.last_seen_at = now
    db.commit()

    return {
        "ok": True,
        "userId": user.id,
        "clientId": client.id,
        "pwaInstalled": client.pwa_installed,
        "materialized": True,
        "device": {
            "type": device.device_type,
            "os": device.os_name,
            "osVersion": device.os_version,
            "browser": device.browser_name,
            "browserVersion": device.browser_version,
        },
    }


@router.get("/feedback")
def pricing_feedback_status(db: Session = Depends(get_db)):
    user = current_user(db)
    client_key = get_client_key()
    client = db.query(UserClient).filter(UserClient.client_key == client_key).first() if client_key else None
    if not client:
        return {"submitted": False, "ratingSubmitted": False}
    row = db.query(ClientPricingFeedback).filter(ClientPricingFeedback.client_id == client.id).first()
    rating_row = db.query(ClientAppRating).filter(ClientAppRating.client_id == client.id).first()
    if not row:
        return {"submitted": False, "ratingSubmitted": bool(rating_row)}
    return {
        "submitted": True,
        "ratingSubmitted": bool(rating_row),
        "savingsValue": row.savings_value,
        "monthlyPrice": row.monthly_price,
        "rating": rating_row.rating if rating_row else None,
        "comment": rating_row.comment if rating_row else "",
        "submittedAt": row.submitted_at.isoformat(),
        "ratingSubmittedAt": rating_row.submitted_at.isoformat() if rating_row else None,
        "userId": user.id,
    }


@router.post("/feedback")
def submit_pricing_feedback(payload: PricingFeedbackPayload, db: Session = Depends(get_db)):
    user = current_user(db)
    client_key = get_client_key()
    client = db.query(UserClient).filter(UserClient.client_key == client_key).first() if client_key else None
    if not client:
        return {"ok": False, "reason": "client_not_found"}

    now = datetime.utcnow()
    row = db.query(ClientPricingFeedback).filter(ClientPricingFeedback.client_id == client.id).first()
    if row is None:
        row = ClientPricingFeedback(client_id=client.id, user_id=user.id)
        db.add(row)
    row.user_id = user.id
    row.savings_value = payload.savingsValue
    row.monthly_price = payload.monthlyPrice
    row.submitted_at = now

    if payload.rating is not None:
        rating_row = db.query(ClientAppRating).filter(ClientAppRating.client_id == client.id).first()
        if rating_row is None:
            rating_row = ClientAppRating(client_id=client.id, user_id=user.id, rating=payload.rating)
            db.add(rating_row)
        rating_row.user_id = user.id
        rating_row.rating = payload.rating
        rating_row.comment = (payload.comment or "").strip() or None
        rating_row.submitted_at = now

    db.commit()
    return {"ok": True, "submitted": True}
