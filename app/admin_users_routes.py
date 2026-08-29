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
from .client_models import (
    AccountClientLink,
    AccountIdentity,
    ClientAppRating,
    ClientDevice,
    ClientPricingFeedback,
    UserClient,
)
from .db import get_db
from .models import FavoriteStore, Store
from .push_models import PushSubscription
from .user_deletion import RegisteredAccountDeletionBlocked, delete_anonymous_user

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/users")
def admin_users(
    request: Request,
    deleted: int | None = None,
    push_user: int | None = None,
    push_sent: int | None = None,
    push_failed: int | None = None,
    custom_push: int | None = None,
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
    links = db.query(AccountClientLink).all()
    identity_by_id = {row.id: row for row in identities}
    link_by_client = {row.client_id: row for row in links}
    push_rows = db.query(PushSubscription).filter(PushSubscription.enabled.is_(True)).all()
    push_by_user: dict[int, list[PushSubscription]] = {}
    for push in push_rows:
        push_by_user.setdefault(push.user_id, []).append(push)
    client_by_key = {client.client_key: client for client in clients}

    logical: dict[tuple[str, int], dict] = {}
    for client in clients:
        link = link_by_client.get(client.id)
        identity = identity_by_id.get(link.identity_id) if link else None
        key = ("account", identity.id) if identity else ("client", client.id)
        row = logical.get(key)
        if row is None:
            canonical_user = identity.user if identity else client.user
            fav_rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == canonical_user.id).all()
            favorites = [store_by_id[fav.store_id] for fav in fav_rows if fav.store_id in store_by_id]
            row = {
                "user": canonical_user,
                "identity": identity,
                "favorites": favorites,
                "clients": [],
                "feedback": None,
                "rating": None,
                "last_seen": client.last_seen_at,
                "push_devices": [
                    {
                        "subscription": push,
                        "client": client_by_key.get(push.client_key or ""),
                    }
                    for push in push_by_user.get(canonical_user.id, [])
                ],
                "push_count": len(push_by_user.get(canonical_user.id, [])),
            }
            logical[key] = row
        row["clients"].append({"client": client, "device": client.device})
        if row["last_seen"] is None or (client.last_seen_at and client.last_seen_at > row["last_seen"]):
            row["last_seen"] = client.last_seen_at
        feedback = feedback_by_client.get(client.id)
        if feedback and (row["feedback"] is None or feedback.submitted_at > row["feedback"].submitted_at):
            row["feedback"] = feedback
        rating = rating_by_client.get(client.id)
        if rating and (row["rating"] is None or rating.submitted_at > row["rating"].submitted_at):
            row["rating"] = rating

    rows = sorted(logical.values(), key=lambda row: row["last_seen"] or datetime.min, reverse=True)
    devices = db.query(ClientDevice).all()
    cutoff = datetime.utcnow() - timedelta(days=7)
    price_counts = Counter(row.monthly_price for row in feedback_rows)
    savings_counts = Counter(row.savings_value for row in feedback_rows)
    rating_counts = Counter(row.rating for row in rating_rows)
    rating_average = round(sum(row.rating for row in rating_rows) / len(rating_rows), 2) if rating_rows else None
    registered_rows = [row for row in rows if row["identity"] is not None]
    anonymous_rows = [row for row in rows if row["identity"] is None]
    stats = {
        "users": len(rows),
        "registered": len(registered_rows),
        "anonymous": len(anonymous_rows),
        "devices": len(devices),
        "installed": sum(1 for c in clients if c.pwa_installed),
        "push_devices": len(push_rows),
        "active7": sum(1 for row in rows if row["last_seen"] and row["last_seen"] >= cutoff),
        "mobile": sum(1 for d in devices if d.device_type == "mobile"),
        "desktop": sum(1 for d in devices if d.device_type == "desktop"),
        "ios": sum(1 for d in devices if d.os_name in {"iOS", "iPadOS"}),
        "android": sum(1 for d in devices if d.os_name == "Android"),
        "with_location": sum(1 for row in rows if row["user"] and row["user"].latitude is not None and row["user"].longitude is not None),
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
        "push_user": push_user,
        "push_sent": push_sent,
        "push_failed": push_failed,
        "custom_push": custom_push,
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
