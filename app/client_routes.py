from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .client_context import get_client_key
from .client_models import ClientDevice, UserClient
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


@router.post("/heartbeat")
def client_heartbeat(payload: ClientHeartbeat, request: Request, db: Session = Depends(get_db)):
    """Record one browser/PWA installation and normalized device metadata."""
    user = current_user(db)
    client_key = get_client_key()
    client = db.query(UserClient).filter(UserClient.client_key == client_key).first() if client_key else None
    if not client:
        return {"ok": True, "userId": user.id, "pwaInstalled": False}

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
        "device": {
            "type": device.device_type,
            "os": device.os_name,
            "osVersion": device.os_version,
            "browser": device.browser_name,
            "browserVersion": device.browser_version,
        },
    }
