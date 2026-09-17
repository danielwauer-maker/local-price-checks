from datetime import datetime

from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.market_activation import activation_overview
from app.models import Store


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _store(db):
    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Brechen",
        postal_code="65611",
        city="Brechen",
        address="Kapellenstraße 88",
        latitude=50.359373,
        longitude=8.183138,
        active=False,
        benchmark_verified=False,
    )
    db.add(store)
    db.flush()
    return store


def _candidate(
    store_id: int,
    key: str,
    *,
    updated_at: datetime,
    status: str,
    address_verified: bool,
    coordinates_verified: bool,
    official_source_verified: bool,
):
    return StoreDiscoveryCandidate(
        discovery_key=key,
        postal_code="65611",
        retailer="ALDI SÜD",
        name="ALDI SÜD Brechen",
        address="Kapellenstraße 88",
        city="Brechen",
        latitude=50.359373,
        longitude=8.183138,
        source="official:aldi_sued" if "official" in key else "osm",
        status=status,
        address_verified=address_verified,
        coordinates_verified=coordinates_verified,
        official_source_verified=official_source_verified,
        matched_store_id=store_id,
        updated_at=updated_at,
    )


def test_activation_overview_prefers_fully_verified_promoted_candidate_over_newer_secondary_source():
    db = _db()
    store = _store(db)
    verified = _candidate(
        store.id,
        "official-brechen",
        updated_at=datetime(2026, 9, 17, 19, 0, 0),
        status="promoted",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    )
    newer_secondary = _candidate(
        store.id,
        "osm-brechen",
        updated_at=datetime(2026, 9, 17, 20, 0, 0),
        status="promoted",
        address_verified=False,
        coordinates_verified=False,
        official_source_verified=False,
    )
    db.add_all([verified, newer_secondary])
    db.commit()

    overview = activation_overview(db, store)

    assert overview["identity_verified"] is True
    assert overview["address_verified"] is True
    assert overview["coordinates_verified"] is True
    assert overview["official_source_verified"] is True
    db.close()


def test_activation_overview_remains_fail_closed_when_no_candidate_has_complete_identity():
    db = _db()
    store = _store(db)
    older_partial = _candidate(
        store.id,
        "official-brechen-partial",
        updated_at=datetime(2026, 9, 17, 19, 0, 0),
        status="promoted",
        address_verified=True,
        coordinates_verified=False,
        official_source_verified=True,
    )
    newer_partial = _candidate(
        store.id,
        "osm-brechen-partial",
        updated_at=datetime(2026, 9, 17, 20, 0, 0),
        status="promoted",
        address_verified=False,
        coordinates_verified=True,
        official_source_verified=False,
    )
    db.add_all([older_partial, newer_partial])
    db.commit()

    overview = activation_overview(db, store)

    assert overview["identity_verified"] is False
    assert overview["address_verified"] is False
    assert overview["coordinates_verified"] is True
    assert overview["official_source_verified"] is False
    db.close()
