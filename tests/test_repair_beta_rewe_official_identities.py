from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.market_activation import StoreActivationState
from app.models import CollectionRun, Store
from scripts.repair_beta_rewe_official_identities import REPAIRS, repair_beta_rewe_identities


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db):
    for spec in REPAIRS:
        store = Store(
            id=spec.store_id,
            retailer="REWE",
            name=f"REWE legacy {spec.store_id}",
            postal_code=spec.postal_code,
            city=spec.city,
            address=spec.old_address,
            latitude=50.0 + spec.store_id / 100,
            longitude=7.0,
            active=True,
            benchmark_verified=True,
            external_id=spec.old_external_id,
            source_url="https://www.openstreetmap.org/",
        )
        db.add(store)
        db.flush()
        run = CollectionRun(
            store_id=store.id,
            source_key="rewe-test",
            status="success",
        )
        db.add(run)
        db.flush()
        db.add(StoreActivationState(
            store_id=store.id,
            lifecycle_status="public",
            identity_verified=True,
            last_test_run_id=run.id,
            published_at=datetime(2026, 1, 1),
        ))
        db.add(StoreDiscoveryCandidate(
            discovery_key=f"official-{spec.external_id}",
            postal_code=spec.postal_code,
            retailer="REWE",
            name=f"REWE official {spec.store_id}",
            address=spec.address,
            city=spec.city,
            latitude=store.latitude,
            longitude=store.longitude,
            source="official:rewe",
            source_external_id=spec.external_id,
            source_url=spec.source_url,
            official_source_verified=True,
        ))
    db.commit()


def test_dry_run_changes_nothing():
    db = _db()
    _seed(db)
    before = [(row.id, row.external_id, row.address, row.source_url) for row in db.query(Store).order_by(Store.id)]
    repair_beta_rewe_identities(db, apply=False)
    after = [(row.id, row.external_id, row.address, row.source_url) for row in db.query(Store).order_by(Store.id)]
    assert after == before
    assert all(row.matched_store_id is None for row in db.query(StoreDiscoveryCandidate))


def test_apply_preserves_ids_publication_runs_and_is_idempotent():
    db = _db()
    _seed(db)
    activation_before = {
        row.store_id: (row.lifecycle_status, row.last_test_run_id, row.published_at)
        for row in db.query(StoreActivationState)
    }
    run_ids_before = [row.id for row in db.query(CollectionRun).order_by(CollectionRun.id)]

    repair_beta_rewe_identities(db, apply=True)
    repair_beta_rewe_identities(db, apply=True)

    assert [row.id for row in db.query(Store).order_by(Store.id)] == [11, 12]
    for spec in REPAIRS:
        store = db.get(Store, spec.store_id)
        assert (store.external_id, store.address, store.source_url) == (
            spec.external_id, spec.address, spec.source_url
        )
        candidate = db.query(StoreDiscoveryCandidate).filter_by(
            source_external_id=spec.external_id
        ).one()
        assert candidate.matched_store_id == spec.store_id
        assert candidate.status == "promoted"
    assert activation_before == {
        row.store_id: (row.lifecycle_status, row.last_test_run_id, row.published_at)
        for row in db.query(StoreActivationState)
    }
    assert run_ids_before == [row.id for row in db.query(CollectionRun).order_by(CollectionRun.id)]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("retailer", "PENNY", "unexpected retailer"),
        ("postal_code", "00000", "unexpected postcode"),
        ("external_id", "unknown", "outside the reviewed states"),
    ),
)
def test_unknown_initial_store_state_aborts(field, value, message):
    db = _db()
    _seed(db)
    setattr(db.get(Store, 11), field, value)
    db.commit()
    with pytest.raises(RuntimeError, match=message):
        repair_beta_rewe_identities(db, apply=True)
    assert db.get(Store, 12).external_id == REPAIRS[1].old_external_id


def test_missing_store_aborts_without_touching_other_store():
    db = _db()
    _seed(db)
    db.query(StoreDiscoveryCandidate).filter_by(matched_store_id=11).update({"matched_store_id": None})
    db.query(StoreActivationState).filter_by(store_id=11).delete()
    db.query(CollectionRun).filter_by(store_id=11).delete()
    db.query(Store).filter_by(id=11).delete()
    db.commit()
    with pytest.raises(RuntimeError, match="Store 11 is missing"):
        repair_beta_rewe_identities(db, apply=True)
    assert db.get(Store, 12).external_id == REPAIRS[1].old_external_id
