from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .client_models import ClientDevice, ClientPricingFeedback, UserClient
from .db import get_db
from .models import FavoriteStore, Store

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    clients = db.query(UserClient).order_by(UserClient.last_seen_at.desc()).all()
    store_by_id = {s.id: s for s in db.query(Store).all()}
    feedback_rows = db.query(ClientPricingFeedback).order_by(ClientPricingFeedback.submitted_at.desc()).all()
    feedback_by_client = {row.client_id: row for row in feedback_rows}
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
            "feedback": feedback_by_client.get(client.id),
        })

    devices = db.query(ClientDevice).all()
    cutoff = datetime.utcnow() - timedelta(days=7)
    price_counts = Counter(row.monthly_price for row in feedback_rows)
    savings_counts = Counter(row.savings_value for row in feedback_rows)
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
        "feedback_total": len(feedback_rows),
    }
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "actor": actor,
        "admin_section": "users",
        "rows": rows,
        "stats": stats,
        "price_counts": price_counts,
        "savings_counts": savings_counts,
    })
