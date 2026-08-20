from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import admin_collector_routes
from app.db import Base
from app.models import CollectionRun, CollectionRunProgress, Store


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _store(SessionLocal):
    db = SessionLocal()
    store = Store(
        retailer="EDEKA",
        name="EDEKA Testmarkt",
        postal_code="00000",
        city="Test",
        address="Teststraße 1",
        active=True,
        benchmark_verified=True,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    store_id = store.id
    db.close()
    return store_id


def test_background_preflight_failure_is_persisted_as_visible_run(monkeypatch):
    SessionLocal = _session_factory()
    store_id = _store(SessionLocal)
    monkeypatch.setattr(admin_collector_routes, "SessionLocal", SessionLocal)

    def fail_before_collection_run(*args, **kwargs):
        raise RuntimeError("EDEKA prospect discovery failed")

    monkeypatch.setattr(admin_collector_routes, "collect_store_from_web", fail_before_collection_run)

    admin_collector_routes._run_store_collection_background(store_id)

    db = SessionLocal()
    runs = db.query(CollectionRun).filter(CollectionRun.store_id == store_id).all()
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "failed"
    assert run.finished_at is not None
    assert run.offers_received == 0
    assert run.offers_imported == 0
    assert run.source_key == "admin-preflight:EDEKA"
    assert "phase=preflight" in run.message
    assert "RuntimeError" in run.message
    assert "EDEKA prospect discovery failed" in run.message
    progress = db.query(CollectionRunProgress).filter_by(run_id=run.id).one()
    assert progress.phase == "preflight"
    assert progress.error_type == "RuntimeError"
    db.close()


def test_background_exception_does_not_duplicate_terminal_collector_run(monkeypatch):
    SessionLocal = _session_factory()
    store_id = _store(SessionLocal)
    monkeypatch.setattr(admin_collector_routes, "SessionLocal", SessionLocal)

    def collector_persists_failure(db, store_name, *, benchmark_context):
        run = CollectionRun(
            store_id=store_id,
            source_key="edeka-test",
            status="failed",
            message="collector-specific failure",
        )
        db.add(run)
        db.commit()
        raise RuntimeError("propagated after persisted run")

    monkeypatch.setattr(admin_collector_routes, "collect_store_from_web", collector_persists_failure)

    admin_collector_routes._run_store_collection_background(store_id)

    db = SessionLocal()
    runs = db.query(CollectionRun).filter(CollectionRun.store_id == store_id).all()
    assert len(runs) == 1
    assert runs[0].source_key == "edeka-test"
    assert runs[0].message == "collector-specific failure"
    db.close()
