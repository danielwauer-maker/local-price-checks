from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_collector_routes import _collector_readiness_context
from app.collection_quality import CollectionQualitySnapshot
from app.db import Base
from app.models import CollectionRun, Store


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _rewe(db):
    store = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
    )
    db.add(store)
    db.flush()
    run = CollectionRun(
        store_id=store.id,
        source_key="rewe:test",
        status="success",
        offers_received=20,
        offers_imported=20,
    )
    db.add(run)
    db.flush()
    return store, run


def test_collector_admin_uses_hardened_external_validation_gate():
    db = _session()
    store, run = _rewe(db)
    db.add(CollectionQualitySnapshot(
        run_id=run.id,
        store_id=store.id,
        retailer=store.retailer,
        run_status="success",
        quality_status="PASS",
        benchmark_status="PASS",
        benchmark_context="PRODUCTION",
        quality_score=99.0,
        metrics_json=json.dumps({
            "external_validation_status": "PASS",
            "external_validation_checked": 9,
        }),
    ))
    db.commit()

    readiness, by_store = _collector_readiness_context(db)

    assert readiness["collector_primary"] == 0
    assert by_store[store.id]["source_strategy"] == "external_primary"
    assert "external_validation_insufficient_samples" in by_store[store.id]["reasons"]


def test_collector_admin_marks_primary_only_after_full_gate():
    db = _session()
    store, run = _rewe(db)
    db.add(CollectionQualitySnapshot(
        run_id=run.id,
        store_id=store.id,
        retailer=store.retailer,
        run_status="success",
        quality_status="PASS",
        benchmark_status="PASS",
        benchmark_context="PRODUCTION",
        quality_score=99.0,
        metrics_json=json.dumps({
            "external_validation_status": "PASS",
            "external_validation_checked": 10,
        }),
    ))
    db.commit()

    readiness, by_store = _collector_readiness_context(db)

    assert readiness["collector_primary"] == 1
    assert by_store[store.id]["source_strategy"] == "collector_primary"
    assert by_store[store.id]["status"] == "READY"
