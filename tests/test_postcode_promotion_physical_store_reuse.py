from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import Store
from app.postcode_coverage_service import promote_candidate_to_store
from app.postcode_reconciliation import group_physical_candidates


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _candidate(
    key: str,
    *,
    source: str,
    external_id: str,
    address: str,
    lat: float,
    status: str = "verified",
) -> StoreDiscoveryCandidate:
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
        status=status,
    )


def test_conflicting_specific_sibling_address_does_not_reuse_legacy_store():
    db = _db()
    official = _candidate(
        "official",
        source="official:lidl",
        external_id="lidl-puderbach-urbacherstr-l264",
        address="Urbacherstraße L264",
        lat=50.592225,
    )
    weak_osm = _candidate(
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
    db.add_all([official, weak_osm, legacy_store])
    db.commit()
    legacy_id = legacy_store.id

    groups = group_physical_candidates([official, weak_osm])
    assert len(groups) == 2

    promoted = promote_candidate_to_store(db, official.id)

    assert promoted.id != legacy_id
    assert promoted.address == "Urbacherstraße L264"
    assert promoted.external_id == "lidl-puderbach-urbacherstr-l264"
    assert db.query(Store).count() == 2

    db.refresh(legacy_store)
    db.refresh(official)
    db.refresh(weak_osm)
    assert legacy_store.address == "Urbacher Straße 31a"
    assert official.matched_store_id == promoted.id
    assert official.status == "promoted"
    assert weak_osm.matched_store_id is None
    assert weak_osm.status == "verified"
    db.close()


def test_rejected_secondary_candidate_does_not_participate_in_physical_grouping():
    official = _candidate(
        "official",
        source="official:lidl",
        external_id="lidl-puderbach-urbacherstr-l264",
        address="Urbacherstraße L264",
        lat=50.592225,
    )
    rejected = _candidate(
        "osm",
        source="osm",
        external_id="node/123",
        address="Urbacherstraße L264",
        lat=50.592225,
        status="rejected",
    )

    groups = group_physical_candidates([official, rejected])

    assert len(groups) == 1
    assert groups[0].members == [official]


def test_compatible_address_range_can_still_collapse_secondary_alias():
    official = _candidate(
        "official",
        source="official:lidl",
        external_id="official-20-22",
        address="Königsberger Str. 20-22",
        lat=50.592225,
    )
    secondary = _candidate(
        "osm",
        source="osm",
        external_id="node/456",
        address="Königsberger Straße 20",
        lat=50.592230,
    )

    groups = group_physical_candidates([official, secondary])

    assert len(groups) == 1
    assert {row.discovery_key for row in groups[0].members} == {"official", "osm"}


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
        address="Urbacherstraße L264",
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
        address="Urbacherstraße L264",
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
