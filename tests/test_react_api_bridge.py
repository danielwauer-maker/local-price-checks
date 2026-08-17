from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.api_main import app
from app.db import Base, SessionLocal, engine
from app.models import FavoriteStore, MasterProduct, Offer, ShoppingItem, Store, UserProfile
from app.seed import seed_stores


def _setup():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_stores(db)
    user = db.query(UserProfile).first()
    if not user:
        user = UserProfile(display_name="React Test", postal_code="57614", city="Steimel", latitude=50.6199, longitude=7.6264, radius_km=50)
        db.add(user)
        db.flush()
    user.latitude = 50.6199
    user.longitude = 7.6264
    user.radius_km = 50

    stores = db.query(Store).filter(Store.active.is_(True), Store.benchmark_verified.is_(True)).limit(2).all()
    product = db.query(MasterProduct).filter_by(normalized_key="react-api-test-product").first()
    if not product:
        product = MasterProduct(name="React API Test Produkt", normalized_key="react-api-test-product")
        db.add(product)
        db.flush()

    today = date.today()
    for idx, store in enumerate(stores):
        offer = db.query(Offer).filter_by(store_id=store.id, master_product_id=product.id, valid_from=today).first()
        if not offer:
            db.add(Offer(store_id=store.id, master_product_id=product.id, price=1.49 + idx, valid_from=today, valid_to=today + timedelta(days=6), local_store_offer=True))

    item = db.query(ShoppingItem).filter_by(user_id=user.id, master_product_id=product.id).first()
    if not item:
        db.add(ShoppingItem(user_id=user.id, master_product_id=product.id, quantity=1))

    db.commit()
    return db, user, product, stores


def test_bootstrap_hydrates_real_prices_for_in_radius_stores_even_before_selection():
    db, user, product, stores = _setup()
    db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).delete()
    db.commit()
    product_id = str(product.id)
    store_ids = {str(s.id) for s in stores}
    db.close()

    client = TestClient(app)
    response = client.get("/api/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected"] == []
    matching = [p for p in payload["prices"] if p["productId"] == product_id]
    assert matching
    assert {p["marketId"] for p in matching}.issubset(store_ids)


def test_backend_plan_uses_selected_markets_and_returns_travel_fields():
    db, user, product, stores = _setup()
    db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).delete()
    db.add(FavoriteStore(user_id=user.id, store_id=stores[0].id))
    db.commit()
    db.close()

    client = TestClient(app)
    response = client.get("/api/plan?max_stores=1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["totalItems"] >= 1
    assert payload["offeredItems"] >= 1
    assert payload["merchandiseTotal"] > 0
    assert payload["total"] >= payload["merchandiseTotal"]
    assert "travelCost" in payload
    assert "travelKm" in payload
    assert len(payload["stops"]) <= 1
