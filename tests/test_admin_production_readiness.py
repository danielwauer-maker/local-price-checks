from __future__ import annotations

import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_data_status_routes import _readiness_context
from app.collection_quality import CollectionQualitySnapshot
from app.db import Base
from app.models import CollectionRun, MasterProduct, Offer, Store


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_readiness_admin_context_shows_na_for_non_applicable_diagnostics(monkeypatch):
    db = _session()
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
        offers_received=1,
        offers_imported=1,
    )
    db.add(run)
    db.flush()
    db.add(CollectionQualitySnapshot(
        run_id=run.id,
        store_id=store.id,
        retailer=store.retailer,
        run_status="success",
        quality_status="PASS",
        benchmark_status="PASS",
        benchmark_context="PRODUCTION",
        quality_score=98.0,
        metrics_json=json.dumps({
            "price_anchor_match_rate": 0.0,
            "page_offer_recall": 0.0,
            "price_anchors_detected": 0,
            "price_anchors_matched": 0,
            "price_anchors_ignored": 0,
            "price_anchors_unmatched": 0,
            "pages_with_unmatched_prices": [],
        }),
    ))
    product = MasterProduct(name="Test", normalized_key="test")
    db.add(product)
    db.flush()
    db.add(Offer(
        store_id=store.id,
        master_product_id=product.id,
        price=1.99,
        valid_from=date(2026, 9, 14),
        valid_to=date(2026, 9, 20),
        local_store_offer=True,
    ))
    db.commit()

    monkeypatch.setattr("app.admin_data_status_routes.app_today", lambda: date(2026, 9, 11))
    context = _readiness_context(db)
    rewe = next(row for row in context["stores"] if row["target_key"] == "rewe-dierdorf")

    assert rewe["source_strategy"] == "collector_primary"
    assert rewe["price_anchor_match_rate"] is None
    assert rewe["page_offer_recall"] is None
    assert rewe["next_week_offers"] == 1
    assert context["next_week_start"] == date(2026, 9, 14)
    assert context["next_week_end"] == date(2026, 9, 20)


def test_readiness_admin_context_keeps_real_zero_when_metric_is_applicable(monkeypatch):
    db = _session()
    store = Store(
        retailer="Lidl",
        name="Lidl Puderbach",
        postal_code="56305",
        city="Puderbach",
        address="Urbacherstr. L264",
        active=True,
        benchmark_verified=True,
    )
    db.add(store)
    db.flush()
    run = CollectionRun(store_id=store.id, source_key="lidl:test", status="success")
    db.add(run)
    db.flush()
    db.add(CollectionQualitySnapshot(
        run_id=run.id,
        store_id=store.id,
        retailer=store.retailer,
        run_status="success",
        quality_status="WARN",
        benchmark_status="WARN",
        benchmark_context="PRODUCTION",
        quality_score=60.0,
        metrics_json=json.dumps({
            "price_anchor_match_rate": 0.0,
            "page_offer_recall": 0.0,
            "price_anchors_detected": 2,
            "price_anchors_unmatched": 2,
        }),
    ))
    db.commit()

    monkeypatch.setattr("app.admin_data_status_routes.app_today", lambda: date(2026, 9, 11))
    context = _readiness_context(db)
    lidl = next(row for row in context["stores"] if row["target_key"] == "lidl-puderbach")

    assert lidl["source_strategy"] == "external_primary"
    assert lidl["price_anchor_match_rate"] == 0.0
    assert lidl["page_offer_recall"] == 0.0
