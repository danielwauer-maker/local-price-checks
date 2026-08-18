from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.client_context import reset_client_key, set_client_key
from app.client_models import UserClient  # noqa: F401
from app.db import Base
from app.models import FavoriteStore, Store, UserProfile
from app.services import current_user


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _as_client(key: str, db):
    token = set_client_key(key)
    try:
        return current_user(db)
    finally:
        reset_client_key(token)


def test_first_client_inherits_legacy_profile_but_second_client_is_isolated():
    db = _db()
    legacy = UserProfile(display_name="Legacy", postal_code="57614", city="Steimel", radius_km=15)
    db.add(legacy)
    db.commit()

    first = _as_client("client_aaaaaaaaaaaaaaaa", db)
    second = _as_client("client_bbbbbbbbbbbbbbbb", db)

    assert first.id == legacy.id
    assert second.id != first.id
    assert second.postal_code is None
    assert db.query(UserClient).count() == 2


def test_market_favorites_remain_separate_per_client_profile():
    db = _db()
    store = Store(
        retailer="REWE",
        name="REWE Test",
        postal_code="57614",
        city="Steimel",
        address="Test 1",
        active=True,
        benchmark_verified=True,
    )
    db.add(store)
    db.commit()

    first = _as_client("client_cccccccccccccccc", db)
    second = _as_client("client_dddddddddddddddd", db)
    db.add(FavoriteStore(user_id=first.id, store_id=store.id))
    db.commit()

    assert db.query(FavoriteStore).filter(FavoriteStore.user_id == first.id).count() == 1
    assert db.query(FavoriteStore).filter(FavoriteStore.user_id == second.id).count() == 0


def test_admin_sidebar_contains_users_and_admin_data_status():
    text = open("app/templates/admin_sidebar.html", encoding="utf-8").read()
    assert 'href="/admin/users"' in text
    assert 'href="/admin/datenstatus"' in text
