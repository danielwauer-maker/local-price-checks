from fastapi.testclient import TestClient

from app.barcode import valid_gtin
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import FavoriteStore, Store, UserProfile
from app.seed import seed_stores
from app.services import favorite_store_ids, selected_store_ids


def setup_module():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_stores(db)
    if not db.query(UserProfile).first():
        db.add(UserProfile(display_name="Test", postal_code="57614", city="Steimel", latitude=50.6199, longitude=7.6264, radius_km=30))
    db.commit()
    db.close()


def test_gtin_check_digit():
    assert valid_gtin("4006381333931")
    assert not valid_gtin("4006381333932")


def test_unverified_active_store_is_hidden_even_when_favorite_row_exists():
    db = SessionLocal()
    user = db.query(UserProfile).first()
    edeka = db.query(Store).filter(Store.retailer == "EDEKA").first()
    existing = db.query(FavoriteStore).filter_by(user_id=user.id, store_id=edeka.id).first()
    if not existing:
        db.add(FavoriteStore(user_id=user.id, store_id=edeka.id))
        db.commit()
    assert edeka.active is True
    assert edeka.benchmark_verified is False
    assert edeka.id not in favorite_store_ids(db, user)
    assert edeka.id not in selected_store_ids(db, user)
    db.close()


def test_mobile_core_routes_render():
    client = TestClient(app)
    for path in ["/", "/maerkte", "/favoriten", "/scanner", "/einkauf", "/angebote", "/sparplan", "/health"]:
        assert client.get(path).status_code == 200
