from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .account_linking import account_profile_for_client
from .client_context import get_client_key, get_legacy_client_key, get_request_method
from .client_models import UserClient
from .clock import app_today
from .geo import haversine_km
from .models import FavoriteStore, Offer, UserProfile

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _unclaimed_profile(db: Session) -> UserProfile | None:
    """Return an existing profile that is not yet attached to any browser client.

    This preserves compatibility with pre-multi-user installations and tests
    that seed a UserProfile before the first browser request. Read-only traffic
    may read such a profile, but never claims it or creates a UserClient.
    """
    claimed_ids = db.query(UserClient.user_id)
    return (
        db.query(UserProfile)
        .filter(~UserProfile.id.in_(claimed_ids))
        .order_by(UserProfile.id)
        .first()
    )


def _guest_profile() -> UserProfile:
    """Return a transient, non-persisted profile for public read-only traffic."""
    return UserProfile(
        display_name="Gast",
        postal_code=None,
        city=None,
        latitude=None,
        longitude=None,
        radius_km=15.0,
    )


def current_user(db: Session, *, persist: bool | None = None) -> UserProfile:
    """Resolve the profile for the current browser/PWA client.

    Existing anonymous clients and verified accounts always resolve normally.
    A previously unseen client is not persisted for safe/read-only HTTP
    methods. If a legacy unclaimed profile already exists, it may be read
    without claiming it; otherwise a transient guest profile is returned.
    UserProfile + UserClient are materialized only on a real personal write.

    ``persist`` can explicitly override the HTTP-method decision. Direct
    server-side/test calls without request context retain the historical
    materializing behavior for backwards compatibility.
    """
    client_key = get_client_key()
    if client_key:
        client = db.query(UserClient).filter(UserClient.client_key == client_key).first()
        if client:
            client.last_seen_at = datetime.utcnow()
            account_user = account_profile_for_client(db, client)
            db.flush()
            return account_user or client.user

        legacy_key = get_legacy_client_key()
        if legacy_key and legacy_key != client_key:
            legacy_client = db.query(UserClient).filter(UserClient.client_key == legacy_key).first()
            if legacy_client:
                legacy_client.client_key = client_key
                legacy_client.last_seen_at = datetime.utcnow()
                if legacy_client.device is not None:
                    legacy_client.device.device_key = client_key
                    legacy_client.device.last_seen_at = legacy_client.last_seen_at
                db.commit()
                db.refresh(legacy_client)
                account_user = account_profile_for_client(db, legacy_client)
                return account_user or legacy_client.user

        if persist is None:
            method = get_request_method()
            persist = False if method in _SAFE_METHODS else True

        if not persist:
            return _unclaimed_profile(db) or _guest_profile()

        user = _unclaimed_profile(db)
        if user is None:
            user = UserProfile(display_name="Anonym", radius_km=15)
            db.add(user)
            db.flush()
            user.display_name = f"Anonym #{user.id}"
        client = UserClient(
            client_key=client_key,
            user_id=user.id,
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
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
