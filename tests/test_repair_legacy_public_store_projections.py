from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.db import Base, create_database_engine
from app.market_activation import StoreActivationState
from app.models import CollectionRun, Store
from scripts.repair_legacy_public_store_projections import (
    REPAIRS,
    repair_legacy_public_projections,
)


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, *, active: bool = False):
    for spec in REPAIRS:
        store = Store(
            id=spec.store_id,
            retailer=spec.retailer,
            name=f"REWE legacy {spec.store_id}",
            postal_code=spec.postal_code,
            city="Altenkirchen" if spec.postal_code == "57610" else "Selters (Taunus)",
            address=spec.address,
            latitude=50.0 + spec.store_id / 1000,
            longitude=7.0,
            active=active,
            benchmark_verified=True,
            external_id=spec.external_id,
            source_url=f"https://example.test/store/{spec.store_id}",
        )
        db.add(store)
        db.flush()
        run = CollectionRun(
            store_id=store.id,
            source_key=f"rewe-{store.id}",
            status="success",
        )
        db.add(run)
        db.flush()
        db.add(
            StoreActivationState(
                store_id=store.id,
                lifecycle_status="public",
                identity_verified=True,
                last_test_run_id=run.id,
                published_at=datetime(2026, 8, 30, 22, 0, 0),
                manually_suspended=False,
            )
        )
    db.commit()


def test_dry_run_preserves_legacy_inactive_projection():
    db = _db()
    _seed(db, active=False)

    reports = repair_legacy_public_projections(db, apply=False)

    assert [row["store_id"] for row in reports] == [9, 10, 13]
    assert all(row["legacy_inactive_public_projection"] for row in reports)
    assert all(not db.get(Store, spec.store_id).active for spec in REPAIRS)


def test_apply_restores_only_active_projection_and_is_idempotent():
    db = _db()
    _seed(db, active=False)
    activation_before = {
        row.store_id: (
            row.lifecycle_status,
            row.identity_verified,
            row.last_test_run_id,
            row.published_at,
            row.manually_suspended,
        )
        for row in db.query(StoreActivationState)
    }
    run_ids_before = [row.id for row in db.query(CollectionRun).order_by(CollectionRun.id)]

    repair_legacy_public_projections(db, apply=True)
    reports = repair_legacy_public_projections(db, apply=False)

    assert all(db.get(Store, spec.store_id).active for spec in REPAIRS)
    assert all(row["already_correct"] for row in reports)
    assert activation_before == {
        row.store_id: (
            row.lifecycle_status,
            row.identity_verified,
            row.last_test_run_id,
            row.published_at,
            row.manually_suspended,
        )
        for row in db.query(StoreActivationState)
    }
    assert run_ids_before == [row.id for row in db.query(CollectionRun).order_by(CollectionRun.id)]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda db: setattr(db.get(Store, 9), "benchmark_verified", False), "not benchmark verified"),
        (
            lambda db: setattr(
                db.query(StoreActivationState).filter_by(store_id=9).one(),
                "published_at",
                None,
            ),
            "not reviewed-public",
        ),
        (
            lambda db: setattr(
                db.query(StoreActivationState).filter_by(store_id=9).one(),
                "manually_suspended",
                True,
            ),
            "not reviewed-public",
        ),
    ),
)
def test_unknown_or_unsafe_state_aborts_atomically(mutation, message):
    db = _db()
    _seed(db, active=False)
    mutation(db)
    db.commit()

    with pytest.raises(RuntimeError, match=message):
        repair_legacy_public_projections(db, apply=True)

    assert all(not db.get(Store, spec.store_id).active for spec in REPAIRS)
