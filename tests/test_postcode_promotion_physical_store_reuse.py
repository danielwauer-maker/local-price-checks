from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import Store
from app.postcode_coverage_service import promote_candidate_to_store


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _candidate(key: str, *, source: str, external_id: str, address: str, lat: float) -> StoreDiscoveryCandidate:
    return StoreDiscoveryCandidate(
        discovery_key=key,
        postal_code="56305",
        retailer="Lidl",
        name="Lidl Puderbach",
        address=address,
        city="Puderbach",
        latitude=lat,
        longitude=7.6085,
        source=source,
        source_external_id=external_id,
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="verified",
    )


def test_promotion_reuses_store_matching_sibling_source_of_same_physical_market():
    db = _db()
    official = _candidate(
        "official",
        source="official:lidl",
        external_id="lidl-puderbach-urbacherstr-l264",
        address="Urbacherstraße L264",
        lat=50.592225,
    )
    osm = _candidate(
        "osm",
        source="osm",
        external_id="node/123",
        address="Urbacher Straße 31a",
        lat=50.592267,
    )
    legacy_store = Store(
        retailer="Lidl",
        name="Lidl Puderbach",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 31a",
        latitude=50.592267,
        longitude=7.6085,
        active=True,
        benchmark_verified=False,
        external_id="node/123",
    )
    db.add_all([official, osm, legacy_store])
    db.commit()
    legacy_id = legacy_store.id

    promoted = promote_candidate_to_store(db, official.id)

    assert promoted.id == legacy_id
    assert db.query(Store).count() == 1
    db.refresh(official)
    db.refresh(osm)
    assert official.matched_store_id == legacy_id
    assert official.status == "promoted"
    assert osm.matched_store_id == legacy_id
    db.close()


def test_promotion_fails_closed_when_two_existing_stores_match_one_physical_group():
    db = _db()
    official = _candidate(
        "official",
        source="official:lidl",
        external_id="lidl-puderbach-urbacherstr-l264",
        address="Urbacherstraße L264",
        lat=50.592225,
    )
    osm = _candidate(
        "osm",
        source="osm",
        external_id="node/123",
        address="Urbacher Straße 31a",
        lat=50.592267,
    )
    official_address_store = Store(
        retailer="Lidl",
        name="Lidl Puderbach Alt A",
        postal_code="56305",
        city="Puderbach",
        address="Urbacherstraße L264",
        latitude=50.592225,
        longitude=7.6085,
        active=True,
        benchmark_verified=False,
        external_id="legacy-a",
    )
    osm_address_store = Store(
        retailer="Lidl",
        name="Lidl Puderbach Alt B",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 31a",
        latitude=50.592267,
        longitude=7.6085,
        active=True,
        benchmark_verified=False,
        external_id="node/123",
    )
    db.add_all([official, osm, official_address_store, osm_address_store])
    db.commit()

    with pytest.raises(ValueError, match="Mehrere bestehende Stores"):
        promote_candidate_to_store(db, official.id)

    assert db.query(Store).count() == 2
    db.close()
