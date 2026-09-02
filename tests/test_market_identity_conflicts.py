import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base
from app.market_identity_conflicts import weak_candidate_promotion_conflict
from app.models import Store
from app.postcode_coverage_service import promote_candidate_to_store


def _db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _candidate(
    db,
    *,
    address="Raiffeisenstraße",
    external_id="way/92219239",
    source="osm",
):
    row = StoreDiscoveryCandidate(
        discovery_key=f"test-{external_id}-{address}",
        postal_code="56587",
        retailer="REWE",
        name="REWE Candidate",
        address=address,
        city="Straßenhaus",
        latitude=50.541989,
        longitude=7.519881,
        source=source,
        source_external_id=external_id,
        source_url="https://www.openstreetmap.org/way/92219239" if source == "osm" else "https://www.rewe.de/",
        status="verified",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    )
    db.add(row)
    db.flush()
    return row


def _official_store(db, row_id=None, *, address="Kirschbüchel 2", external_id="1940425"):
    row = Store(
        id=row_id,
        retailer="REWE",
        name=f"REWE Official {external_id}",
        postal_code="56587",
        city="Straßenhaus",
        address=address,
        latitude=50.54205,
        longitude=7.51990,
        active=True,
        benchmark_verified=False,
        external_id=external_id,
        source_url=f"https://www.rewe.de/marktseite/strassenhaus/{external_id}/",
    )
    db.add(row)
    db.flush()
    return row


def test_wrong_address_osm_candidate_is_blocked_before_store_creation():
    db = _db()
    _official_store(db)
    candidate = _candidate(db)
    db.commit()

    conflict = weak_candidate_promotion_conflict(db, candidate)
    assert conflict.blocked is True
    assert "räumliche Nähe reichen nicht" in conflict.reason

    with pytest.raises(ValueError, match="Möglicher Doppelmarkt"):
        promote_candidate_to_store(db, candidate.id)
    assert db.query(Store).count() == 1
    assert candidate.status == "verified"
    assert candidate.matched_store_id is None


def test_matching_address_osm_candidate_reuses_existing_official_store():
    db = _db()
    official = _official_store(db)
    candidate = _candidate(db, address="Kirschbüchel 2")
    db.commit()

    promoted = promote_candidate_to_store(db, candidate.id)

    assert promoted.id == official.id
    assert candidate.matched_store_id == official.id
    assert db.query(Store).count() == 1


def test_real_second_branch_with_own_official_id_is_created():
    db = _db()
    _official_store(db)
    candidate = _candidate(
        db,
        address="Raiffeisenstraße 8",
        external_id="998877",
        source="official:rewe",
    )
    db.commit()

    promoted = promote_candidate_to_store(db, candidate.id)

    assert promoted.external_id == "998877"
    assert db.query(Store).count() == 2


def test_weak_alias_uses_matching_official_candidate_instead_of_creating_osm_store():
    db = _db()
    _official_store(db)
    weak = _candidate(db, address="Raiffeisenstraße 8")
    official = _candidate(
        db,
        address="Raiffeisenstraße 8",
        external_id="998877",
        source="official:rewe",
    )
    db.commit()

    conflict = weak_candidate_promotion_conflict(db, weak)
    assert conflict.blocked is True
    assert f"Kandidat {official.id}" in conflict.reason
    with pytest.raises(ValueError, match="offiziellen Datensatz"):
        promote_candidate_to_store(db, weak.id)

    promoted = promote_candidate_to_store(db, official.id)
    assert promoted.external_id == "998877"
    assert db.query(Store).count() == 2


def test_different_official_ids_at_same_address_remain_two_stores():
    db = _db()
    _official_store(db, address="Gemeinsame Straße 1", external_id="111")
    candidate = _candidate(
        db,
        address="Gemeinsame Str. 1",
        external_id="222",
        source="official:rewe",
    )
    db.commit()

    promote_candidate_to_store(db, candidate.id)

    assert {row.external_id for row in db.query(Store).all()} == {"111", "222"}


def test_weak_candidate_stays_manual_when_multiple_strong_branches_exist():
    db = _db()
    _official_store(db, address="Bahnhofstraße 30", external_id="8534500")
    _official_store(db, address="Dammweg 10", external_id="2500021")
    candidate = _candidate(db, address="Unklare Straße 1", external_id="node/123")
    db.commit()

    conflict = weak_candidate_promotion_conflict(db, candidate)

    assert conflict.blocked is True
    assert conflict.canonical_store is None
    assert candidate.status == "verified"
    assert candidate.matched_store_id is None
