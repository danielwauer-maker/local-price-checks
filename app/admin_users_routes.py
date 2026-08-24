from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import _admin
from .client_models import AccountIdentity, ClientAppRating, ClientDevice, ClientPricingFeedback, UserClient
from .db import get_db
from .models import FavoriteStore, Store
from .user_deletion import RegisteredAccountDeletionBlocked, delete_anonymous_user

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/users")
def admin_users(
    request: Request,
    deleted: int | None = None,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    clients = db.query(UserClient).order_by(UserClient.last_seen_at.desc()).all()
    store_by_id = {s.id: s for s in db.query(Store).all()}
    feedback_rows = db.query(ClientPricingFeedback).order_by(ClientPricingFeedback.submitted_at.desc()).all()
    rating_rows = db.query(ClientAppRating).order_by(ClientAppRating.submitted_at.desc()).all()
    feedback_by_client = {row.client_id: row for row in feedback_rows}
    rating_by_client = {row.client_id: row for row in rating_rows}
    identities = db.query(AccountIdentity).all()
    identity_by_user = {row.user_id: row for row in identities}
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
            "rating": rating_by_client.get(client.id),
            "identity": identity_by_user.get(user.id),
        })

    devices = db.query(ClientDevice).all()
    cutoff = datetime.utcnow() - timedelta(days=7)
    price_counts = Counter(row.monthly_price for row in feedback_rows)
    savings_counts = Counter(row.savings_value for row in feedback_rows)
    rating_counts = Counter(row.rating for row in rating_rows)
    rating_average = round(sum(row.rating for row in rating_rows) / len(rating_rows), 2) if rating_rows else None
    stats = {
        "users": len(clients),
        "registered": len({row.user_id for row in identities}),
        "anonymous": sum(1 for c in clients if c.user_id not in identity_by_user),
        "devices": len(devices),
        "installed": sum(1 for c in clients if c.pwa_installed),
        "active7": sum(1 for c in clients if c.last_seen_at and c.last_seen_at >= cutoff),
        "mobile": sum(1 for d in devices if d.device_type == "mobile"),
        "desktop": sum(1 for d in devices if d.device_type == "desktop"),
        "ios": sum(1 for d in devices if d.os_name in {"iOS", "iPadOS"}),
        "android": sum(1 for d in devices if d.os_name == "Android"),
        "with_location": sum(1 for c in clients if c.user and c.user.latitude is not None and c.user.longitude is not None),
        "feedback_total": len(feedback_rows),
        "rating_total": len(rating_rows),
        "rating_average": rating_average,
        "comments_total": sum(1 for row in rating_rows if row.comment),
    }
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "actor": actor,
        "admin_section": "users",
        "rows": rows,
        "stats": stats,
        "price_counts": price_counts,
        "savings_counts": savings_counts,
        "rating_counts": rating_counts,
        "rating_rows": rating_rows,
        "deleted": deleted,
    })


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(
    user_id: int,
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    if confirm != f"DELETE-{user_id}":
        raise HTTPException(400, "Löschbestätigung ist ungültig")

    try:
        result = delete_anonymous_user(db, user_id)
    except RegisteredAccountDeletionBlocked as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc

    if result is None:
        db.rollback()
        raise HTTPException(404, "Nutzer nicht gefunden")

    audit(
        db,
        "anonymous_user_deleted",
        "user_profile",
        result.user_id,
        f"display_name={result.display_name}; clients={result.client_count}",
        actor,
    )
    db.commit()
    return RedirectResponse(f"/admin/users?deleted={result.user_id}", status_code=303)
