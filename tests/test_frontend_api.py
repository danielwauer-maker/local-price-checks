from fastapi.testclient import TestClient

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


def test_basket_api_persists_quantity():
    user_id, product_id = _seed()
    client = TestClient(app)
    response = client.put(f"/api/basket/{product_id}", json={"quantity": 3})
    assert response.status_code == 200
    db = SessionLocal()
    row = db.query(ShoppingItem).filter_by(user_id=user_id, master_product_id=product_id).first()
    assert row is not None and row.quantity == 3
    db.close()


def test_verified_store_toggle_api():
    user_id, _ = _seed()
    db = SessionLocal()
    store = db.query(Store).filter(Store.active.is_(True), Store.benchmark_verified.is_(True)).first()
    assert store is not None
    store_id = store.id
    before = db.query(FavoriteStore).filter_by(user_id=user_id, store_id=store_id).first() is not None
    db.close()

    client = TestClient(app)
    response = client.post(f"/api/stores/{store_id}/toggle")
    assert response.status_code == 200
    assert response.json()["selected"] is (not before)
