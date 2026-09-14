from datetime import date

from fastapi.testclient import TestClient

from app import canonical_lokero_market_routes, lokero_routes
from app.api_main import app
from app.db import Base, SessionLocal, engine
from app.models import MasterProduct, Offer, Store, UserProfile


def test_next_period_returns_only_released_local_offers_in_following_calendar_week(monkeypatch):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    user = UserProfile(
        display_name="Upcoming Offer Test",
        latitude=50.62,
        longitude=7.62,
        radius_km=15,
    )
    store = Store(
        retailer="TEST",
        name="Upcoming Offer Test Store",
        postal_code="56269",
        city="Dierdorf",
        address="Testweg 1",
        latitude=50.621,
        longitude=7.621,
        active=True,
        benchmark_verified=True,
    )
    products = [
        MasterProduct(name=f"Period Test {suffix}", normalized_key=f"period-test-{suffix}")
        for suffix in ("current", "next", "later", "online")
    ]
    db.add_all([user, store, *products])
    db.flush()
    offers = [
        Offer(store_id=store.id, master_product_id=products[0].id, price=1.00, valid_from=date(2026, 9, 7), valid_to=date(2026, 9, 13), local_store_offer=True),
        Offer(store_id=store.id, master_product_id=products[1].id, price=2.00, valid_from=date(2026, 9, 14), valid_to=date(2026, 9, 19), local_store_offer=True),
        Offer(store_id=store.id, master_product_id=products[2].id, price=3.00, valid_from=date(2026, 9, 21), valid_to=date(2026, 9, 26), local_store_offer=True),
        Offer(store_id=store.id, master_product_id=products[3].id, price=4.00, valid_from=date(2026, 9, 14), valid_to=date(2026, 9, 19), local_store_offer=False),
    ]
    db.add_all(offers)
    db.commit()

    monkeypatch.setattr(lokero_routes, "app_today", lambda: date(2026, 9, 13))
    monkeypatch.setattr(canonical_lokero_market_routes, "current_user", lambda _db: user)
    monkeypatch.setattr(canonical_lokero_market_routes, "reviewer_device", lambda _db: None)
    monkeypatch.setattr(
        canonical_lokero_market_routes,
        "get_feature_flags",
        lambda _db: {"offers": True, "normal_price_badges": False, "savings": False},
    )
    monkeypatch.setattr(canonical_lokero_market_routes, "_road_distance_map", lambda *_args: {})

    try:
        current = canonical_lokero_market_routes.canonical_offers(
            market_ids=str(store.id), period="current", limit=250, db=db
        )
        upcoming = canonical_lokero_market_routes.canonical_offers(
            market_ids=str(store.id), period="next", limit=250, db=db
        )

        assert [row["product"]["name"] for row in current] == ["Period Test current"]
        assert [row["product"]["name"] for row in upcoming] == ["Period Test next"]
        assert upcoming[0]["validFrom"] == "2026-09-14"
        assert upcoming[0]["validUntil"] == "2026-09-19"
    finally:
        for offer in offers:
            db.delete(offer)
        for product in products:
            db.delete(product)
        db.delete(store)
        db.delete(user)
        db.commit()
        db.close()


def test_next_offer_week_is_calendar_bound_even_without_imported_offers(monkeypatch):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    monkeypatch.setattr(lokero_routes, "app_today", lambda: date(2026, 9, 13))
    try:
        assert lokero_routes.offer_week(period="next", db=db) == {
            "from": "2026-09-14",
            "until": "2026-09-20",
        }
    finally:
        db.close()


def test_public_offer_api_rejects_unknown_periods():
    Base.metadata.create_all(engine)
    response = TestClient(app).get("/api/lokero/offers", params={"period": "later"})
    assert response.status_code == 422
