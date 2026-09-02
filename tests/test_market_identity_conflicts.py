from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base
from app.market_identity_conflicts import weak_candidate_promotion_conflict
from app.models import Store


def _db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _candidate(db, *, address="Raiffeisenstraße", external_id="way/92219239"):
    row = StoreDiscoveryCandidate(
        discovery_key=f"test-{external_id}-{address}",
        postal_code="56587",
        retailer="REWE",
        name="REWE",
        address=address,
        city="Straßenhaus",
        latitude=50.541989,
        longitude=7.519881,
        source="osm",
        source_external_id=external_id,
        status="verified",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    )
    db.add(row)
    db.flush()
    return row


def test_wrong_address_osm_candidate_is_blocked_when_one_official_store_exists():
    db = _db()
    db.add(Store(
        retailer="REWE",
        name="REWE Dennis Weirich",
        postal_code="56587",
        city="Straßenhaus",
        address="Kirschbüchel 2",
        active=True,
        benchmark_verified=False,
        external_id="1940425",
    ))
    db.commit()
    candidate = _candidate(db)

    conflict = weak_candidate_promotion_conflict(db, candidate)
    assert conflict.blocked is True
    assert conflict.canonical_store.name == "REWE Dennis Weirich"
    assert "zweite Filiale" in conflict.reason
    db.close()


def test_matching_official_candidate_proves_distinct_second_branch():
    db = _db()
    db.add(Store(
        retailer="REWE",
        name="REWE Existing",
        postal_code="56587",
        city="Straßenhaus",
        address="Kirschbüchel 2",
        active=True,
        benchmark_verified=False,
        external_id="1940425",
    ))
    db.add(StoreDiscoveryCandidate(
        discovery_key="official-second",
        postal_code="56587",
        retailer="REWE",
        name="REWE Second",
        address="Raiffeisenstraße",
        city="Straßenhaus",
        latitude=50.54,
        longitude=7.52,
        source="official:rewe",
        source_external_id="999999",
        status="verified",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    ))
    db.commit()
    candidate = _candidate(db)

    conflict = weak_candidate_promotion_conflict(db, candidate)
    assert conflict.blocked is False
    db.close()


def test_multiple_strong_store_identities_never_assign_weak_candidate_by_postcode_alone():
    db = _db()
    for name, address, external_id in (
        ("REWE A", "Bahnhofstraße 30", "8534500"),
        ("REWE B", "Dammweg 10", "2500021"),
    ):
        db.add(Store(
            retailer="REWE",
            name=name,
            postal_code="57610",
            city="Altenkirchen",
            address=address,
            active=True,
            benchmark_verified=False,
            external_id=external_id,
        ))
    db.commit()
    candidate = StoreDiscoveryCandidate(
        discovery_key="ak-weak",
        postal_code="57610",
        retailer="REWE",
        name="REWE map",
        address="Unklar 1",
        city="Altenkirchen",
        latitude=50.68,
        longitude=7.65,
        source="osm",
        source_external_id="way/123",
        status="verified",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    )
    db.add(candidate)
    db.commit()

    assert weak_candidate_promotion_conflict(db, candidate).blocked is False
    db.close()
