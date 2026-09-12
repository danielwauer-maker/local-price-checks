from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collection_quality import (
    BenchmarkContext,
    RETAILER_QUALITY_POLICIES,
    evaluate_collection_quality,
)
from app.db import Base
from app.extractor_adapter import ImportSummary
from app.models import CollectionRun, Store


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _aldi_store_and_run(db):
    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf benchmark test",
        postal_code="56269",
        city="Dierdorf",
        address="Teststr. 1",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    run = CollectionRun(store_id=store.id, source_key="aldi-sued:test", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    return store, run


def _rows(count):
    return [SimpleNamespace(product_name=f"ALDI Produkt {idx}") for idx in range(count)]


def test_aldi_sued_baseline_matches_verified_current_week_without_weakening_ratios():
    policy = RETAILER_QUALITY_POLICIES["ALDI SÜD"]

    assert policy.expected_min_offers == 100
    assert policy.pass_count_ratio == 0.80
    assert policy.fail_count_ratio == 0.30


def test_aldi_sued_95_imported_offers_pass_volume_benchmark():
    db = _session()
    store, run = _aldi_store_and_run(db)

    _quality_status, benchmark_status, _score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=_rows(97),
        summary=ImportSummary(received=97, imported=95, rejected_quality=2),
        images_saved=0,
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert benchmark_status == "PASS"
    assert metrics["expected_min_offers"] == 100
    assert metrics["expected_offer_ratio"] == 95.0
    assert metrics["benchmark_reasons"] == []


def test_aldi_sued_material_coverage_drop_still_warns():
    db = _session()
    store, run = _aldi_store_and_run(db)

    _quality_status, benchmark_status, _score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=_rows(60),
        summary=ImportSummary(received=60, imported=60),
        images_saved=0,
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert benchmark_status == "WARN"
    assert "offer_count_below_pass_floor" in metrics["benchmark_reasons"]
