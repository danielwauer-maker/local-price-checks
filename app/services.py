from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .account_linking import account_profile_for_client
from .client_context import get_client_key, get_legacy_client_key, get_request_method
from .client_models import AccountClientLink, UserClient
from .clock import app_today
from .geo import haversine_km
from .models import FavoriteStore, Offer, Store, UserProfile
from .physical_market_identity import canonical_store_map

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _unclaimed_profile(db: Session) -> UserProfile | None:
    """Return an existing profile that is not yet attached to any browser client."""
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
    """Resolve the profile for the current browser/PWA client."""
    client_key = get_client_key()
    if client_key:
        if persist is None:
            method = get_request_method()
            persist = False if method in _SAFE_METHODS else True
        client = db.query(UserClient).filter(UserClient.client_key == client_key).first()
        if client:
            account_user = account_profile_for_client(db, client)
            if persist:
                now = datetime.utcnow()
                client.last_seen_at = now
                link = db.query(AccountClientLink).filter(AccountClientLink.client_id == client.id).first()
                if link is not None:
                    link.last_seen_at = now
                    link.identity.last_seen_at = now
                db.flush()
            return account_user or client.user

        legacy_key = get_legacy_client_key()
        if legacy_key and legacy_key != client_key:
            legacy_client = db.query(UserClient).filter(UserClient.client_key == legacy_key).first()
            if legacy_client:
                if persist:
                    legacy_client.client_key = client_key
                    legacy_client.last_seen_at = datetime.utcnow()
                    if legacy_client.device is not None:
                        legacy_client.device.device_key = client_key
                        legacy_client.device.last_seen_at = legacy_client.last_seen_at
                    db.commit()
                    db.refresh(legacy_client)
                account_user = account_profile_for_client(db, legacy_client)
                return account_user or legacy_client.user

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

    user = db.query(UserProfile).first()
    if not user:
        user = UserProfile(display_name="Local User", radius_km=15)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _canonical_mapping(db: Session) -> dict[int, Store]:
    return canonical_store_map(db.query(Store).all())


def favorite_store_ids(db: Session, user: UserProfile) -> list[int]:
    """Return public favorites as canonical physical market ids."""
    return favorite_and_selected_store_ids(db, user)[0]


def favorite_and_selected_store_ids(db: Session, user: UserProfile) -> tuple[list[int], list[int]]:
    """Resolve canonical favorite and in-radius ids in one bounded pass."""
    from .market_activation import store_is_public

    mapping = _canonical_mapping(db)
    rows = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()
    favorite_ids: list[int] = []
    selected_ids: list[int] = []
    seen: set[int] = set()
    for row in rows:
        store = mapping.get(row.store_id, row.store)
        if not store_is_public(store) or store.id in seen:
            continue
        seen.add(store.id)
        favorite_ids.append(store.id)
        in_radius = True
        if None not in (user.latitude, user.longitude, store.latitude, store.longitude):
            in_radius = haversine_km(user.latitude, user.longitude, store.latitude, store.longitude) <= user.radius_km
        if in_radius:
            selected_ids.append(store.id)
    return favorite_ids, selected_ids


def selected_store_ids(db: Session, user: UserProfile) -> list[int]:
    """Return canonical released favorite markets inside the search radius."""
    return favorite_and_selected_store_ids(db, user)[1]


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
