from fastapi.testclient import TestClient

from app.api_main import app
from app.coverage_models import CoverageRegion
from app.coverage_service import normalize_retailer, seed_initial_coverage
from app.db import Base, SessionLocal, engine
from app.engine_v140.source_registry import source_for_store_record
from app.models import Store


def test_initial_coverage_region_is_seeded_and_public():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_initial_coverage(db)
    region = db.query(CoverageRegion).filter(CoverageRegion.name == "Westerwald – Steimel/Dierdorf").first()
    assert region is not None
    assert region.status == "live"
    db.close()

    response = TestClient(app).get("/api/coverage")
    assert response.status_code == 200
    payload = response.json()
    assert any(row["name"] == "Westerwald – Steimel/Dierdorf" for row in payload)


def test_known_retailers_are_normalized_for_discovery():
    assert normalize_retailer("REWE Markt") == "REWE"
    assert normalize_retailer("Netto Marken-Discount") == "Netto Marken-Discount"
    assert normalize_retailer("ALDI SÜD") == "ALDI SÜD"
    assert normalize_retailer("Unbekannter Laden") is None


def test_new_store_can_use_dynamic_retailer_source_without_static_registry():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter(Store.name == "Automatischer Lidl Testmarkt").first()
    if not store:
        store = Store(
            retailer="Lidl",
            name="Automatischer Lidl Testmarkt",
            postal_code="56068",
            city="Koblenz",
            address="Teststraße 1",
            latitude=50.36,
            longitude=7.59,
            active=True,
            benchmark_verified=False,
        )
        db.add(store)
        db.commit()
        db.refresh(store)
    source = source_for_store_record(store)
    assert source is not None
    assert source.retailer == "Lidl"
    assert source.store_name == store.name
    assert source.key.startswith("auto_")
    db.delete(store)
    db.commit()
    db.close()
