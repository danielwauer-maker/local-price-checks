from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .client_context import get_client_key
from .client_models import UserClient
from .clock import app_today
from .geo import haversine_km
from .models import FavoriteStore, Offer, UserProfile


def current_user(db: Session) -> UserProfile:
    """Return the persistent profile for the current browser/PWA client.

    Before multi-client tracking existed, LocalPrices used the first UserProfile
    for every request. The first browser seen after this migration inherits that
    legacy profile so existing favorites/location are preserved. Every later
    client receives its own profile.
    """
    client_key = get_client_key()
    if client_key:
        client = db.query(UserClient).filter(UserClient.client_key == client_key).first()
        if client:
            client.last_seen_at = datetime.utcnow()
            db.flush()
            return client.user

        existing_clients = db.query(UserClient).count()
        user = db.query(UserProfile).first() if existing_clients == 0 else None
        if user is None:
            user = UserProfile(display_name=f"Nutzer {db.query(UserProfile).count() + 1}", radius_km=15)
            db.add(user)
            db.flush()
        client = UserClient(client_key=client_key, user_id=user.id, first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow())
        db.add(client)
        db.commit()
        db.refresh(user)
        return user

    # Startup/background jobs do not have an HTTP client identity.
    user = db.query(UserProfile).first()
    if not user:
        user = UserProfile(display_name="Local User", radius_km=15)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def favorite_store_ids(db: Session, user: UserProfile) -> list[int]:
    """Return persistent market favorites independent of search area or QA release."""
    rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
    ids: list[int] = []
    for row in rows:
        store = row.store
        if not store.active:
            continue
        ids.append(store.id)
    return ids


def selected_store_ids(db: Session, user: UserProfile) -> list[int]:
    """Return favorite markets that are released for offers and inside the search radius.

    benchmark_verified is the user-facing release gate only. Unverified markets
    may still be collected and audited in the admin workflow, but their data is
    never used for offers or shopping-plan calculations.
    """
    favorite_ids = set(favorite_store_ids(db, user))
    if not favorite_ids:
        return []

    rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
    ids: list[int] = []
    for row in rows:
        store = row.store
        if store.id not in favorite_ids or not store.benchmark_verified:
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
    today = app_today()
    q = db.query(Offer).filter(Offer.store_id.in_(ids), Offer.local_store_offer.is_(True))
    if view == "next":
        q = q.filter(Offer.valid_from > today, Offer.valid_from <= today + timedelta(days=14))
    else:
        q = q.filter(Offer.valid_from <= today, Offer.valid_to >= today)
    return q.order_by(Offer.price.asc()).all()
