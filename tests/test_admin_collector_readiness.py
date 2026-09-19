from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_collector_routes import (
    _collector_readiness_context,
    _current_physical_prospect,
    _latest_physical_run,
    _physical_offer_week_observability,
)
from app.collection_quality import CollectionQualitySnapshot
from app.db import Base
from app.models import CollectionRun, MasterProduct, Offer, Store
from app.prospect_models import Prospect


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

    assert readiness["scope_key"] == "beta-1"
    assert readiness["target_count"] == 12
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



def test_collector_physical_helpers_surface_alias_run_and_prospect_history():
    db = _session()
    canonical = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
    )
    alias = Store(
        retailer="REWE",
        name="REWE Dierdorf legacy",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Straße 20-22",
        active=False,
        benchmark_verified=False,
        external_id="321019",
    )
    db.add_all([canonical, alias])
    db.flush()

    run = CollectionRun(
        store_id=alias.id,
        source_key="legacy-alias",
        status="success",
        offers_received=11,
        offers_imported=10,
        started_at=datetime(2026, 9, 18, 8, 0, 0),
    )
    prospect = Prospect(
        store_id=alias.id,
        period_key="current",
        source_url="https://www.rewe.de/angebote/dierdorf/321019/test/",
        pdf_url="web-snapshot://captured-session/v3/legacy",
        local_path="",
        page_count=3,
        active=True,
        fetched_at=datetime(2026, 9, 18, 8, 5, 0),
    )
    db.add_all([run, prospect])
    db.commit()

    physical_run = _latest_physical_run(db, [canonical.id, alias.id])
    physical_prospect = _current_physical_prospect(db, [canonical, alias], "current")

    assert physical_run is not None
    assert physical_run.id == run.id
    assert physical_run.store_id == alias.id
    assert physical_prospect is not None
    assert physical_prospect.id == prospect.id
    assert physical_prospect.store_id == alias.id


def test_collector_week_observability_is_alias_safe_and_keeps_weeks_separate():
    db = _session()
    canonical = Store(
        retailer="REWE",
        name="REWE:XL observability canonical",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
    )
    alias = Store(
        retailer="REWE",
        name="REWE observability legacy",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Straße 20-22",
        active=False,
        benchmark_verified=False,
        external_id="321019",
    )
    current_product = MasterProduct(name="Current Product", normalized_key="current-product")
    next_product = MasterProduct(name="Next Product", normalized_key="next-product")
    db.add_all([canonical, alias, current_product, next_product])
    db.flush()

    current_kwargs = dict(
        master_product_id=current_product.id,
        price=1.99,
        valid_from=date(2026, 9, 14),
        valid_to=date(2026, 9, 20),
        source_url="https://www.rewe.de/angebote/dierdorf/321019/test/",
    )
    db.add_all([
        Offer(store_id=canonical.id, **current_kwargs),
        Offer(store_id=alias.id, **current_kwargs),
        Offer(
            store_id=alias.id,
            master_product_id=next_product.id,
            price=2.49,
            valid_from=date(2026, 9, 21),
            valid_to=date(2026, 9, 27),
            source_url="https://www.rewe.de/angebote/dierdorf/321019/next/",
        ),
    ])
    db.commit()

    observation = _physical_offer_week_observability(
        db,
        [canonical.id, alias.id],
        today=date(2026, 9, 19),
    )

    assert observation["current"]["window_from"] == date(2026, 9, 14)
    assert observation["current"]["window_to"] == date(2026, 9, 20)
    assert observation["next"]["window_from"] == date(2026, 9, 21)
    assert observation["next"]["window_to"] == date(2026, 9, 27)
    assert observation["current"]["count"] == 1
    assert observation["next"]["count"] == 1
    assert observation["current"]["ranges"] == [(date(2026, 9, 14), date(2026, 9, 20))]
    assert observation["next"]["ranges"] == [(date(2026, 9, 21), date(2026, 9, 27))]
    assert observation["source_urls"] == [
        "https://www.rewe.de/angebote/dierdorf/321019/next/",
        "https://www.rewe.de/angebote/dierdorf/321019/test/",
    ]
