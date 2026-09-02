from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import model_registry  # noqa: F401 - register all direct Store references
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base
from app.market_activation import StoreActivationState
from app.market_admin_delete import delete_false_store, preview_false_store_delete
from app.models import CollectionRun, Store


def _db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _false_store(db):
    store = Store(
        retailer="REWE",
        name="REWE (2)",
        address="Raiffeisenstraße",
        postal_code="56587",
        city="Straßenhaus",
        latitude=50.541989,
        longitude=7.519881,
        active=True,
        benchmark_verified=False,
        external_id="way/92219239",
        source_url="http://www.rewe.de",
    )
    db.add(store)
    db.flush()
    candidate = StoreDiscoveryCandidate(
        discovery_key="osm-test",
        postal_code="56587",
        retailer="REWE",
        name="REWE",
        address="Raiffeisenstraße",
        city="Straßenhaus",
        latitude=50.541989,
        longitude=7.519881,
        source="osm",
        source_external_id="way/92219239",
        status="promoted",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        matched_store_id=store.id,
    )
    db.add(candidate)
    db.add(StoreActivationState(store_id=store.id, lifecycle_status="promoted", identity_verified=True))
    db.commit()
    return store.id, candidate.id


def test_prepublic_false_store_with_only_workflow_metadata_can_be_deleted():
    db = _db()
    store_id, candidate_id = _false_store(db)
    store = db.get(Store, store_id)

    preview = preview_false_store_delete(db, store)
    assert preview.allowed is True
    assert preview.dependent_counts["store_discovery_candidates"] == 1
    assert preview.dependent_counts["store_activation_states"] == 1

    result = delete_false_store(db, store)
    assert result.allowed is True
    db.commit()

    assert db.get(Store, store_id) is None
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    assert candidate is not None
    assert candidate.status == "rejected"
    assert candidate.matched_store_id is None
    assert "dauerhaft gelöscht" in candidate.verification_note
    assert db.query(StoreActivationState).filter_by(store_id=store_id).count() == 0
    db.close()


def test_store_with_collection_history_is_not_hard_deleted():
    db = _db()
    store_id, _ = _false_store(db)
    db.add(CollectionRun(store_id=store_id, source_key="test", status="success"))
    db.commit()

    store = db.get(Store, store_id)
    preview = preview_false_store_delete(db, store)
    assert preview.allowed is False
    assert any("collection_runs" in blocker for blocker in preview.blockers)

    result = delete_false_store(db, store)
    assert result.allowed is False
    assert db.get(Store, store_id) is not None
    db.close()


def test_public_store_is_never_hard_deleted():
    db = _db()
    store_id, _ = _false_store(db)
    store = db.get(Store, store_id)
    store.benchmark_verified = True
    db.commit()

    preview = preview_false_store_delete(db, store)
    assert preview.allowed is False
    assert any("öffentlich" in blocker for blocker in preview.blockers)
    db.close()
