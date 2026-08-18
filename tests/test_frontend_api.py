from fastapi.testclient import TestClient

import app.api_routes as api_routes
from app.api_main import app
from app.db import Base, SessionLocal, engine
from app.models import FavoriteStore, MasterProduct, ShoppingItem, Store, UserProfile
from app.seed import seed_stores


def _seed():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_stores(db)
    user = db.query(UserProfile).first()
    if not user:
        user = UserProfile(display_name="Frontend API", postal_code="57614", city="Steimel", latitude=50.6199, longitude=7.6264, radius_km=15)
        db.add(user)
        db.commit()
        db.refresh(user)
    product = db.query(MasterProduct).first()
    if not product:
        product = MasterProduct(name="API Test Product", normalized_key="api-test-product")
        db.add(product)
        db.commit()
        db.refresh(product)
    db.close()
    return user.id, product.id


def test_bootstrap_exposes_real_app_state():
    _seed()
    client = TestClient(app)
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert "location" in payload
    assert "markets" in payload
    assert "products" in payload
    assert "prices" in payload
    assert "basket" in payload
    assert "activeSelected" in payload


def test_basket_api_persists_quantity():
    user_id, product_id = _seed()
    client = TestClient(app)
    response = client.put(f"/api/basket/{product_id}", json={"quantity": 3})
    assert response.status_code == 200
    db = SessionLocal()
    row = db.query(ShoppingItem).filter_by(user_id=user_id, master_product_id=product_id).first()
    assert row is not None and row.quantity == 3
    db.close()


def test_verified_store_toggle_api(monkeypatch):
    user_id, _ = _seed()
    db = SessionLocal()
    store = db.query(Store).filter(Store.active.is_(True), Store.benchmark_verified.is_(True)).first()
    assert store is not None
    store_id = store.id
    existing = db.query(FavoriteStore).filter_by(user_id=user_id, store_id=store_id).first()
    if existing:
        db.delete(existing)
        db.commit()
    db.close()

    monkeypatch.setattr(api_routes, "_collect_store_background", lambda _store_id: None)
    client = TestClient(app)
    response = client.post(f"/api/stores/{store_id}/toggle")
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected"] is True
    assert str(store_id) in payload["selectedIds"]
    assert str(store_id) in payload["activeSelectedIds"]
    assert payload["released"] is True
    assert payload["refreshStarted"] is True


def test_unverified_active_store_is_persistent_favorite_but_not_released_for_offers(monkeypatch):
    user_id, _ = _seed()
    db = SessionLocal()
    user = db.get(UserProfile, user_id)
    assert user is not None
    user.latitude = 50.6199
    user.longitude = 7.6264
    user.radius_km = 50

    store = Store(
        retailer="Testmarkt",
        name="Unverifizierter aktiver Testmarkt",
        postal_code="57614",
        city="Steimel",
        address="Teststraße 2",
        latitude=50.62,
        longitude=7.63,
        active=True,
        benchmark_verified=False,
        external_id="unverified-favorite-test",
    )
    db.add(store)
    db.commit()
    store_id = store.id
    db.close()

    monkeypatch.setattr(api_routes, "_collect_store_background", lambda _store_id: None)
    client = TestClient(app)
    response = client.post(f"/api/stores/{store_id}/toggle")
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected"] is True
    assert str(store_id) in payload["selectedIds"]
    assert str(store_id) not in payload["activeSelectedIds"]
    assert payload["released"] is False
    assert payload["prices"] == []
    assert payload["refreshStarted"] is True

    bootstrap = client.get("/api/bootstrap").json()
    assert str(store_id) in bootstrap["selected"]
    assert str(store_id) not in bootstrap["activeSelected"]

    store_offers = client.get(f"/api/stores/{store_id}/offers").json()
    assert store_offers["status"] == "qa_pending"
    assert store_offers["prices"] == []

    db = SessionLocal()
    db.query(FavoriteStore).filter_by(user_id=user_id, store_id=store_id).delete()
    db.query(Store).filter_by(id=store_id).delete()
    db.commit()
    db.close()


def test_favorite_market_survives_outside_search_radius():
    user_id, _ = _seed()
    db = SessionLocal()
    user = db.get(UserProfile, user_id)
    assert user is not None
    user.latitude = 50.6199
    user.longitude = 7.6264
    user.radius_km = 5

    store = Store(
        retailer="Testmarkt",
        name="Testmarkt außerhalb Suchgebiet",
        postal_code="10115",
        city="Berlin",
        address="Teststraße 1",
        latitude=52.52,
        longitude=13.405,
        active=True,
        benchmark_verified=False,
        external_id="outside-test",
    )
    db.add(store)
    db.flush()
    db.add(FavoriteStore(user_id=user_id, store_id=store.id))
    db.commit()
    store_id = store.id
    db.close()

    client = TestClient(app)
    payload = client.get("/api/bootstrap").json()
    market_ids = {row["id"] for row in payload["markets"]}
    assert str(store_id) in payload["selected"]
    assert str(store_id) in market_ids
    assert str(store_id) not in payload["activeSelected"]

    db = SessionLocal()
    db.query(FavoriteStore).filter_by(user_id=user_id, store_id=store_id).delete()
    db.query(Store).filter_by(id=store_id).delete()
    db.commit()
    db.close()
