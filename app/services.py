from __future__ import annotations

from datetime import date, timedelta
from sqlalchemy.orm import Session

from .geo import haversine_km
from .models import FavoriteStore, Offer, UserProfile


def current_user(db: Session) -> UserProfile:
    user = db.query(UserProfile).first()
    if not user:
        user = UserProfile(display_name="Local User", radius_km=15)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def selected_store_ids(db: Session, user: UserProfile) -> list[int]:
    rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
    ids = []
    for row in rows:
        store = row.store
        if not store.active or not store.benchmark_verified:
            continue
        if None not in (user.latitude, user.longitude, store.latitude, store.longitude):
            if haversine_km(user.latitude, user.longitude, store.latitude, store.longitude) > user.radius_km:
                continue
        ids.append(store.id)
    return ids


def offers_for_selected_stores(db: Session, user: UserProfile, view: str = "current"):
    ids = selected_store_ids(db, user)
    if not ids:
        return []
    today = date.today()
    q = db.query(Offer).filter(Offer.store_id.in_(ids), Offer.local_store_offer.is_(True))
    if view == "next":
        q = q.filter(Offer.valid_from > today, Offer.valid_from <= today + timedelta(days=14))
    else:
        q = q.filter(Offer.valid_from <= today, Offer.valid_to >= today)
    return q.order_by(Offer.price.asc()).all()
