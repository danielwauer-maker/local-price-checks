from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import Store
from app.postcode_coverage_service import (
    INITIAL_B2_POSTCODES,
    candidate_ready_for_promotion,
    promote_candidate_to_store,
    seed_initial_postcode_coverage,
    set_postcode_enabled,
    stage_postcode_candidates,
)


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_initial_b2_postcodes_are_seeded_enabled_once():
    db = _db()
    seed_initial_postcode_coverage(db)
    seed_initial_postcode_coverage(db)
    rows = db.query(CoveragePostalCode).order_by(CoveragePostalCode.postal_code).all()
    assert {row.postal_code for row in rows} == set(INITIAL_B2_POSTCODES)
    assert all(row.enabled for row in rows)
    db.close()


def test_postcode_toggle_requires_exact_five_digits():
    db = _db()
    row = set_postcode_enabled(db, "56269", True)
    assert row.enabled is True
    try:
        set_postcode_enabled(db, "5626", True)
    except ValueError as exc:
        assert "fünf" in str(exc)
    else:
        raise AssertionError("invalid postcode must fail")
    db.close()


def test_discovery_stages_candidates_without_creating_public_store(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        "app.postcode_coverage_service.discover_postcode_supermarkets",
        lambda postal_code: [
            {
                "discovery_key": "candidate-1",
                "postal_code": postal_code,
                "retailer": "Lidl",
                "name": "Lidl Testmarkt",
                "address": "Urbacher Straße 31a",
                "city": "Puderbach",
                "latitude": 50.592267,
                "longitude": 7.608759,
                "source": "osm",
                "source_external_id": "node/123",
                "source_url": "https://example.invalid/lidl",
            }
        ],
    )
    created, updated = stage_postcode_candidates(db, "56305")
    assert (created, updated) == (1, 0)
    assert db.query(StoreDiscoveryCandidate).count() == 1
    assert db.query(Store).count() == 0
    candidate = db.query(StoreDiscoveryCandidate).one()
    assert candidate.address_verified is False
    assert candidate.coordinates_verified is False
    assert candidate.official_source_verified is False
    db.close()


def test_candidate_cannot_be_promoted_before_all_identity_gates():
    db = _db()
    candidate = StoreDiscoveryCandidate(
        discovery_key="candidate-gates",
        postal_code="56305",
        retailer="Lidl",
        name="Lidl Testmarkt",
        address="Urbacher Straße 31a",
        city="Puderbach",
        latitude=50.592267,
        longitude=7.608759,
    )
    db.add(candidate)
    db.commit()
    assert candidate_ready_for_promotion(candidate) is False
    try:
        promote_candidate_to_store(db, candidate.id)
    except ValueError as exc:
        assert "verifiziert" in str(exc)
    else:
        raise AssertionError("unverified candidate must not be promoted")
    assert db.query(Store).count() == 0
    db.close()


def test_fully_verified_candidate_promotes_with_exact_address_and_coordinates():
    db = _db()
    candidate = StoreDiscoveryCandidate(
        discovery_key="candidate-promote",
        postal_code="56305",
        retailer="Lidl",
        name="Lidl Puderbach",
        address="Urbacher Straße 31a",
        city="Puderbach",
        latitude=50.592267,
        longitude=7.608759,
        source_external_id="node/456",
        source_url="https://example.invalid/lidl",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="verified",
    )
    db.add(candidate)
    db.commit()
    store = promote_candidate_to_store(db, candidate.id)
    assert store.postal_code == "56305"
    assert store.address == "Urbacher Straße 31a"
    assert store.latitude == 50.592267
    assert store.longitude == 7.608759
    assert store.benchmark_verified is False
    assert candidate.matched_store_id == store.id
    assert candidate.status == "promoted"
    db.close()
