from datetime import timedelta

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api_main import app
from app.clock import app_today
from app.client_models import UserClient
from app.db import Base, get_db
from app.models import FavoriteStore, MasterProduct, Offer, ProductAdminData, ProductCategory, Store, UserProfile
from app.lokero_state_routes import AlternativesBatchPayload


CLIENT_KEY = "performance-test-client-0001"


def _database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    db = factory()
    today = app_today()
    user = UserProfile(
        display_name="Performance Test",
        latitude=50.6199,
        longitude=7.6264,
        radius_km=30,
    )
    category = ProductCategory(name="Performance Food", slug="performance-food", active=True)
    db.add_all([user, category])
    db.flush()
    stores = [
        Store(
            retailer=f"Retailer {index}",
            name=f"Performance Store {index}",
            postal_code="56269",
            city="Dierdorf",
            address=f"Testweg {index}",
            latitude=50.62 + index * 0.001,
            longitude=7.62 + index * 0.001,
            active=True,
            benchmark_verified=True,
        )
        for index in range(5)
    ]
    db.add_all(stores)
    db.flush()
    db.add_all(FavoriteStore(user_id=user.id, store_id=store.id) for store in stores)
    products = [
        MasterProduct(
            name=f"Test Vollmilch {index:03d}",
            brand=f"Marke {index % 8}",
            package_size="1 l",
            normalized_key=f"performance-milk-{index:03d}",
        )
        for index in range(80)
    ]
    db.add_all(products)
    db.flush()
    db.add_all(ProductAdminData(master_product_id=product.id, category_id=category.id) for product in products)
    for product_index, product in enumerate(products):
        for offset in range(3):
            store = stores[(product_index + offset) % len(stores)]
            db.add(Offer(
                store_id=store.id,
                master_product_id=product.id,
                price=round(0.89 + (product_index % 20) * 0.04 + offset * 0.01, 2),
                valid_from=today - timedelta(days=1),
                valid_to=today + timedelta(days=5),
                local_store_offer=True,
            ))
    db.add(UserClient(client_key=CLIENT_KEY, user_id=user.id))
    db.flush()
    db.info.pop("spareno_new_offer_push_candidates", None)
    db.commit()
    db.close()
    return engine, factory, [product.id for product in products[:5]]


def _request_with_query_count(engine, request):
    queries = 0

    def count(*_args):
        nonlocal queries
        queries += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = request()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return response, queries


def test_offer_page_serialization_has_bounded_query_count(monkeypatch):
    engine, factory, _ = _database()

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(
        "app.canonical_lokero_market_routes._road_distance_map",
        lambda _user, stores: {store.id: 1.0 for store in stores},
    )
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app, headers={"x-localprices-client": CLIENT_KEY})
        response, queries = _request_with_query_count(
            engine,
            lambda: client.get("/api/lokero/offers?limit=200"),
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()

    assert response.status_code == 200
    assert len(response.json()) == 200
    assert queries <= 12


def test_alternatives_batch_replaces_http_n_plus_one_with_bounded_queries():
    engine, factory, product_ids = _database()

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app, headers={"x-localprices-client": CLIENT_KEY})
        response, queries = _request_with_query_count(
            engine,
            lambda: client.post(
                "/api/lokero/list/alternatives/batch",
                json={"productIds": product_ids, "limit": 3},
            ),
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()

    assert response.status_code == 200
    alternatives = response.json()["alternatives"]
    assert set(alternatives) == {str(product_id) for product_id in product_ids}
    assert all(len(rows) == 3 for rows in alternatives.values())
    assert all(str(product_id) not in {row["product"]["id"] for row in alternatives[str(product_id)]} for product_id in product_ids)
    assert queries <= 12


def test_alternatives_batch_caps_input_size():
    with pytest.raises(ValidationError):
        AlternativesBatchPayload(productIds=list(range(1, 52)), limit=3)
