from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import admin_collector_routes
from app.collection_quality import BenchmarkContext
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


def _rewe_store(SessionLocal):
    db = SessionLocal()
    store = Store(
        retailer="REWE",
        name="REWE Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
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
        raise RuntimeError("EDEKA web collection failed")

    monkeypatch.setattr(admin_collector_routes, "collect_edeka_web_for_store", fail_before_collection_run)

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
    assert "EDEKA web collection failed" in run.message
    progress = db.query(CollectionRunProgress).filter_by(run_id=run.id).one()
    assert progress.phase == "preflight"
    assert progress.error_type == "RuntimeError"
    db.close()


def test_background_exception_does_not_duplicate_terminal_collector_run(monkeypatch):
    SessionLocal = _session_factory()
    store_id = _store(SessionLocal)
    monkeypatch.setattr(admin_collector_routes, "SessionLocal", SessionLocal)

    def collector_persists_failure(db, store, *, benchmark_context):
        run = CollectionRun(
            store_id=store_id,
            source_key="edeka-test",
            status="failed",
            message="collector-specific failure",
        )
        db.add(run)
        db.commit()
        raise RuntimeError("propagated after persisted run")

    monkeypatch.setattr(admin_collector_routes, "collect_edeka_web_for_store", collector_persists_failure)

    admin_collector_routes._run_store_collection_background(store_id)

    db = SessionLocal()
    runs = db.query(CollectionRun).filter(CollectionRun.store_id == store_id).all()
    assert len(runs) == 1
    assert runs[0].source_key == "edeka-test"
    assert runs[0].message == "collector-specific failure"
    db.close()


def test_manual_verified_rewe_collection_runs_authoritative_completion_hook(monkeypatch):
    SessionLocal = _session_factory()
    store_id = _rewe_store(SessionLocal)
    monkeypatch.setattr(admin_collector_routes, "SessionLocal", SessionLocal)

    calls = {}
    result = {"offers": ["fresh-row"]}
    summary = object()

    def collect(db, store_name, *, benchmark_context):
        calls["collector_context"] = benchmark_context
        calls["store_name"] = store_name
        return result, summary, CollectionRun(
            store_id=store_id,
            source_key="rewe-test",
            status="success",
        )

    def reconcile(db, store, actual_result, actual_summary, run):
        calls["reconciled"] = True
        calls["reconcile_store_id"] = store.id
        calls["result"] = actual_result
        calls["summary"] = actual_summary
        calls["run"] = run
        return 0

    monkeypatch.setattr(admin_collector_routes, "collect_store_from_web", collect)
    monkeypatch.setattr(admin_collector_routes, "_reconcile_rewe_manual_collection", reconcile)

    admin_collector_routes._run_store_collection_background(store_id)

    assert calls["collector_context"] == BenchmarkContext.PRODUCTION
    assert calls["store_name"] == "REWE Dierdorf"
    assert calls["reconciled"] is True
    assert calls["reconcile_store_id"] == store_id
    assert calls["result"] is result
    assert calls["summary"] is summary
    assert calls["run"].status == "success"
