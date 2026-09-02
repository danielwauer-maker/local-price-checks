from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.market_activation import StoreActivationState
from app.models import Store
from app.seed import seed_stores


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _fellenzer(db, *, benchmark_verified: bool, active: bool = True):
    store = Store(
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Str. 35",
        latitude=50.6,
        longitude=7.611,
        active=active,
        benchmark_verified=benchmark_verified,
        external_id="071378",
    )
    db.add(store)
    db.commit()
    return store


def test_seed_does_not_overwrite_existing_publication_decision():
    db = _db()
    store = _fellenzer(db, benchmark_verified=True)

    seed_stores(db)
    db.refresh(store)

    assert store.benchmark_verified is True
    db.close()


def test_seed_repairs_legacy_public_state_mismatch_after_restart():
    db = _db()
    store = _fellenzer(db, benchmark_verified=False)
    state = StoreActivationState(
        store_id=store.id,
        lifecycle_status="public",
        identity_verified=True,
        manually_suspended=False,
        published_at=datetime.utcnow(),
    )
    db.add(state)
    db.commit()

    seed_stores(db)
    db.refresh(store)
    db.refresh(state)

    assert store.active is True
    assert store.benchmark_verified is True
    assert state.lifecycle_status == "public"
    db.close()


def test_seed_repairs_corrupted_lifecycle_when_prior_publication_is_proven():
    db = _db()
    store = _fellenzer(db, benchmark_verified=False)
    state = StoreActivationState(
        store_id=store.id,
        lifecycle_status="quality_review",
        identity_verified=True,
        manually_suspended=False,
        published_at=datetime.utcnow(),
    )
    db.add(state)
    db.commit()

    seed_stores(db)
    db.refresh(store)
    db.refresh(state)

    assert store.benchmark_verified is True
    assert state.lifecycle_status == "public"
    db.close()


def test_seed_does_not_auto_publish_quality_only_market_without_publication_proof():
    db = _db()
    store = _fellenzer(db, benchmark_verified=False)
    state = StoreActivationState(
        store_id=store.id,
        lifecycle_status="quality_passed",
        identity_verified=True,
        manually_suspended=False,
        published_at=None,
    )
    db.add(state)
    db.commit()

    seed_stores(db)
    db.refresh(store)
    db.refresh(state)

    assert store.benchmark_verified is False
    assert state.lifecycle_status == "quality_passed"
    db.close()


def test_seed_never_reactivates_manually_suspended_store():
    db = _db()
    store = _fellenzer(db, benchmark_verified=False, active=True)
    state = StoreActivationState(
        store_id=store.id,
        lifecycle_status="quality_review",
        identity_verified=True,
        manually_suspended=True,
        suspension_reason="operator hold",
        published_at=datetime.utcnow(),
    )
    db.add(state)
    db.commit()

    seed_stores(db)
    db.refresh(store)
    db.refresh(state)

    assert store.benchmark_verified is False
    assert state.lifecycle_status == "quality_review"
    db.close()


def test_new_seed_store_still_uses_bootstrap_verification_default():
    db = _db()

    seed_stores(db)

    rewe = db.query(Store).filter_by(name="REWE:XL Hundertmark").one()
    edeka = db.query(Store).filter_by(name="EDEKA Fellenzer").one()
    assert rewe.benchmark_verified is True
    assert edeka.benchmark_verified is False
    db.close()
