from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.activity_models import ClientActivityDay, ClientFeatureUsage, ClientUsageSession
from app.activity_service import record_client_activity
from app.client_models import UserClient
from app.db import Base
from app.models import UserProfile


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(db, *, pwa: bool = False):
    user = UserProfile(display_name="Usage Test", radius_km=15)
    db.add(user)
    db.flush()
    client = UserClient(
        client_key="device_usage_test_1234567890",
        user_id=user.id,
        pwa_installed=pwa,
    )
    db.add(client)
    db.commit()
    return user, client


def test_page_views_are_daily_aggregates_not_raw_url_history():
    db = _db()
    user, client = _client(db)
    now = datetime(2026, 8, 23, 18, 0, 0)

    record_client_activity(db, client=client, user_id=user.id, kind="page_view", page="home", now=now)
    record_client_activity(db, client=client, user_id=user.id, kind="page_view", page="offers", now=now + timedelta(minutes=2))

    assert db.query(ClientUsageSession).count() == 1
    session = db.query(ClientUsageSession).one()
    assert session.page_views == 2
    assert session.entry_page == "home"
    assert session.last_page == "offers"

    day = db.query(ClientActivityDay).one()
    assert day.session_count == 1
    assert day.page_views == 2
    assert day.home_views == 1
    assert day.offers_views == 1
    assert day.favorite_products_count == 0
    assert day.favorite_stores_count == 0
    assert day.shopping_items_count == 0

    # Analytics schema intentionally has no raw path/query/payload field.
    column_names = {column.name for column in ClientActivityDay.__table__.columns}
    assert "path" not in column_names
    assert "url" not in column_names
    assert "query" not in column_names
    assert "payload" not in column_names


def test_session_timeout_starts_a_second_session():
    db = _db()
    user, client = _client(db)
    now = datetime(2026, 8, 23, 18, 0, 0)

    record_client_activity(db, client=client, user_id=user.id, kind="page_view", page="home", now=now)
    record_client_activity(db, client=client, user_id=user.id, kind="pulse", page="home", now=now + timedelta(minutes=10))
    record_client_activity(db, client=client, user_id=user.id, kind="page_view", page="stores", now=now + timedelta(minutes=41))

    assert db.query(ClientUsageSession).count() == 2
    day = db.query(ClientActivityDay).one()
    assert day.session_count == 2
    assert day.page_views == 2


def test_cross_midnight_activity_counts_one_active_session_on_new_day():
    db = _db()
    user, client = _client(db)
    before_midnight = datetime(2026, 8, 23, 23, 55, 0)

    record_client_activity(db, client=client, user_id=user.id, kind="page_view", page="home", now=before_midnight)
    record_client_activity(db, client=client, user_id=user.id, kind="pulse", page="home", now=before_midnight + timedelta(minutes=10))

    days = db.query(ClientActivityDay).order_by(ClientActivityDay.activity_date).all()
    assert len(days) == 2
    assert days[0].session_count == 1
    assert days[1].session_count == 1
    assert db.query(ClientUsageSession).count() == 1


def test_feature_usage_is_allowlisted_and_aggregated():
    db = _db()
    user, client = _client(db, pwa=True)
    now = datetime(2026, 8, 23, 18, 0, 0)

    record_client_activity(
        db,
        client=client,
        user_id=user.id,
        kind="feature",
        feature="favorite_product_toggle",
        now=now,
    )
    record_client_activity(
        db,
        client=client,
        user_id=user.id,
        kind="feature",
        feature="favorite_product_toggle",
        now=now + timedelta(minutes=1),
    )
    record_client_activity(
        db,
        client=client,
        user_id=user.id,
        kind="feature",
        feature="not_allowed",
        now=now + timedelta(minutes=2),
    )

    rows = db.query(ClientFeatureUsage).all()
    assert len(rows) == 1
    assert rows[0].feature == "favorite_product_toggle"
    assert rows[0].use_count == 2

    session = db.query(ClientUsageSession).one()
    assert session.pwa is True
