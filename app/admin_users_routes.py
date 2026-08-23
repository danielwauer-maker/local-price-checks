from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .client_models import ClientDevice, UserClient
from .db import get_db
from .models import FavoriteStore, Store

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    clients = db.query(UserClient).order_by(UserClient.last_seen_at.desc()).all()
    store_by_id = {s.id: s for s in db.query(Store).all()}
    rows = []
    for client in clients:
        user = client.user
        fav_rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
        favorites = [store_by_id[row.store_id] for row in fav_rows if row.store_id in store_by_id]
        rows.append({
            "client": client,
            "device": client.device,
            "user": user,
            "favorites": favorites,
        })

    devices = db.query(ClientDevice).all()
    cutoff = datetime.utcnow() - timedelta(days=7)
    stats = {
        "users": len(clients),
        "devices": len(devices),
        "installed": sum(1 for c in clients if c.pwa_installed),
        "active7": sum(1 for c in clients if c.last_seen_at and c.last_seen_at >= cutoff),
        "mobile": sum(1 for d in devices if d.device_type == "mobile"),
        "desktop": sum(1 for d in devices if d.device_type == "desktop"),
        "ios": sum(1 for d in devices if d.os_name in {"iOS", "iPadOS"}),
        "android": sum(1 for d in devices if d.os_name == "Android"),
        "with_location": sum(1 for c in clients if c.user and c.user.latitude is not None and c.user.longitude is not None),
    }
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "actor": actor,
        "admin_section": "users",
        "rows": rows,
        "stats": stats,
    })
