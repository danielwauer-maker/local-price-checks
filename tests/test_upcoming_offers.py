from datetime import date, timedelta

from app import upcoming_routes
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import FavoriteStore, MasterProduct, Offer, Store, UserProfile
from app.services import offers_for_selected_stores


def test_next_week_only_returns_released_selected_future_offers(monkeypatch):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    old_override = settings.local_date_override
    settings.local_date_override = "2026-08-24"
    user = None
    store = None
    product = None
    try:
        user = UserProfile(
            display_name="Next Week Test",
            latitude=50.62,
            longitude=7.62,
            radius_km=15,
        )
        db.add(user)
        db.flush()
        store = Store(
            retailer="TEST",
            name="Next Week Test Store",
            postal_code="57614",
            city="Steimel",
            address="Testweg 1",
            latitude=50.621,
            longitude=7.621,
            active=True,
            benchmark_verified=True,
        )
        db.add(store)
        db.flush()
        db.add(FavoriteStore(user_id=user.id, store_id=store.id))
        product = MasterProduct(name="Next Week Test Product", normalized_key="next-week-test-product")
        db.add(product)
        db.flush()

        today = date(2026, 8, 24)
        current = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=3.49,
            valid_from=today - timedelta(days=1),
            valid_to=today + timedelta(days=2),
            local_store_offer=True,
        )
        upcoming = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=2.49,
            valid_from=today + timedelta(days=7),
            valid_to=today + timedelta(days=13),
            local_store_offer=True,
        )
        too_far = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=1.99,
            valid_from=today + timedelta(days=21),
            valid_to=today + timedelta(days=27),
            local_store_offer=True,
        )
        db.add_all([current, upcoming, too_far])
        db.commit()

        rows = offers_for_selected_stores(db, user, "next")
        assert [row.id for row in rows] == [upcoming.id]

        monkeypatch.setattr(upcoming_routes, "current_user", lambda _db: user)
        payload = upcoming_routes.upcoming_offers(db)
        assert payload["count"] == 1
        assert payload["startsOn"] == "2026-08-31"
        assert payload["prices"][0]["productId"] == str(product.id)
        assert payload["prices"][0]["marketId"] == str(store.id)
        assert payload["prices"][0]["validFrom"] == "2026-08-31"
        assert payload["prices"][0]["offer"]["price"] == 2.49
    finally:
        settings.local_date_override = old_override
        if store is not None:
            db.query(Offer).filter(Offer.store_id == store.id).delete(synchronize_session=False)
            db.query(FavoriteStore).filter(FavoriteStore.store_id == store.id).delete(synchronize_session=False)
            db.delete(store)
        if product is not None:
            db.delete(product)
        if user is not None:
            db.delete(user)
        db.commit()
        db.close()
