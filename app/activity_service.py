from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .activity_models import ClientActivityDay, ClientFeatureUsage, ClientUsageSession
from .client_models import UserClient
from .models import FavoriteProduct, FavoriteStore, ShoppingItem

SESSION_TIMEOUT = timedelta(minutes=30)

PAGE_FIELDS = {
    "home": "home_views",
    "offers": "offers_views",
    "favorites": "favorites_views",
    "shopping": "shopping_views",
    "stores": "stores_views",
    "settings": "settings_views",
    "store_detail": "store_detail_views",
    "other": "other_views",
}

FEATURES = {
    "favorite_product_toggle",
    "favorite_store_toggle",
    "favorite_alternative_toggle",
    "shopping_item_add",
    "shopping_item_remove",
    "shopping_item_quantity",
    "shopping_item_check",
    "shopping_clear",
    "location_update",
    "radius_update",
    "profile_update",
}


def _state_counts(db: Session, user_id: int) -> tuple[int, int, int]:
    favorites = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user_id).count()
    stores = db.query(FavoriteStore).filter(FavoriteStore.user_id == user_id).count()
    shopping = db.query(ShoppingItem).filter(ShoppingItem.user_id == user_id).count()
    return favorites, stores, shopping


def _daily_row(db: Session, client_id: int, now: datetime) -> ClientActivityDay:
    day = now.date()
    row = (
        db.query(ClientActivityDay)
        .filter(ClientActivityDay.client_id == client_id, ClientActivityDay.activity_date == day)
        .first()
    )
    if row is None:
        row = ClientActivityDay(
            client_id=client_id,
            activity_date=day,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(row)
        db.flush()
    return row


def _session(db: Session, client: UserClient, now: datetime, page: str | None) -> tuple[ClientUsageSession, bool]:
    latest = (
        db.query(ClientUsageSession)
        .filter(ClientUsageSession.client_id == client.id)
        .order_by(ClientUsageSession.last_seen_at.desc())
        .first()
    )
    is_new = latest is None or now - latest.last_seen_at > SESSION_TIMEOUT
    if is_new:
        latest = ClientUsageSession(
            client_id=client.id,
            started_at=now,
            last_seen_at=now,
            page_views=0,
            entry_page=page,
            last_page=page,
            pwa=bool(client.pwa_installed),
        )
        db.add(latest)
        db.flush()
    return latest, is_new


def record_client_activity(
    db: Session,
    *,
    client: UserClient,
    user_id: int,
    kind: str,
    page: str | None = None,
    feature: str | None = None,
    now: datetime | None = None,
) -> dict[str, int | str | bool | None]:
    """Record a coarse, privacy-minimal client activity aggregate.

    ``kind`` is one of ``page_view``, ``pulse`` or ``feature``. Pages and
    features are allow-listed by the API layer; this function also normalizes
    unknown pages to ``other`` and ignores unknown feature names.
    """

    now = now or datetime.utcnow()
    normalized_page = page if page in PAGE_FIELDS else ("other" if page else None)

    session, new_session = _session(db, client, now, normalized_page)
    session.last_seen_at = now
    if normalized_page:
        session.last_page = normalized_page

    day = _daily_row(db, client.id, now)
    day.last_seen_at = now
    if new_session:
        day.session_count += 1

    if kind == "page_view":
        session.page_views += 1
        day.page_views += 1
        field = PAGE_FIELDS[normalized_page or "other"]
        setattr(day, field, getattr(day, field) + 1)

    if kind == "feature" and feature in FEATURES:
        usage = (
            db.query(ClientFeatureUsage)
            .filter(ClientFeatureUsage.client_id == client.id, ClientFeatureUsage.feature == feature)
            .first()
        )
        if usage is None:
            usage = ClientFeatureUsage(
                client_id=client.id,
                feature=feature,
                use_count=1,
                first_used_at=now,
                last_used_at=now,
            )
            db.add(usage)
        else:
            usage.use_count += 1
            usage.last_used_at = now

    favorite_products, favorite_stores, shopping_items = _state_counts(db, user_id)
    day.favorite_products_count = favorite_products
    day.favorite_stores_count = favorite_stores
    day.shopping_items_count = shopping_items

    db.commit()

    return {
        "sessionId": session.id,
        "newSession": new_session,
        "page": normalized_page,
        "favoriteProducts": favorite_products,
        "favoriteStores": favorite_stores,
        "shoppingItems": shopping_items,
    }
