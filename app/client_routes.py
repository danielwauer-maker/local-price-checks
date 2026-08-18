from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .client_context import get_client_key
from .client_models import UserClient
from .db import get_db
from .services import current_user

router = APIRouter(prefix="/api/client")


class ClientHeartbeat(BaseModel):
    pwaInstalled: bool = False
    platform: str = ""


@router.post("/heartbeat")
def client_heartbeat(payload: ClientHeartbeat, request: Request, db: Session = Depends(get_db)):
    """Record that a browser/PWA client is active and whether it runs standalone."""
    user = current_user(db)
    client_key = get_client_key()
    client = db.query(UserClient).filter(UserClient.client_key == client_key).first() if client_key else None
    if client:
        now = datetime.utcnow()
        client.last_seen_at = now
        if payload.pwaInstalled:
            client.pwa_installed = True
            client.pwa_last_seen_at = now
        client.platform = (payload.platform or "")[:80] or client.platform
        client.user_agent = (request.headers.get("user-agent") or "")[:1000] or client.user_agent
        db.commit()
    return {"ok": True, "userId": user.id, "pwaInstalled": bool(client and client.pwa_installed)}
