import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collection_quality import CollectionQualitySnapshot
from app.db import Base
from app.models import CollectionRun, Store
from app.production_readiness import (
    ExternalOfferSample,
    TARGET_MARKETS,
    assess_store_readiness,
    build_multi_market_readiness,
    next_week_window,
    persist_external_validation_result,
    quality_metric_for_display,
    validate_external_samples,
)


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _ready_store(
    db,
    *,
    retailer="REWE",
    name="REWE Dierdorf",
    city="Dierdorf",
    external_id="321019",
    benchmark_context="PRODUCTION",
    external_validation=True,
):
    store = Store(
        retailer=retailer,
        name=name,
        postal_code="56269",
        city=city,
        address="Test 1",
        active=True,
        benchmark_verified=True,
        external_id=external_id,
    )
    db.add(store)
    db.flush()
    run = CollectionRun(
        store_id=store.id,
        source_key="test",
        status="success",
        offers_received=206,
        offers_imported=206,
    )
    db.add(run)
    db.flush()
    metrics = {}
    if external_validation:
        metrics = {
            "external_validation_status": "PASS",
            "external_validation_score": 100.0,
            "external_validation_checked": 10,
            "external_validation_matched": 10,
            "external_validation_missing": 0,
            "external_validation_online_only_leaks": 0,
        }
    db.add(
        CollectionQualitySnapshot(
            run_id=run.id,
            store_id=store.id,
            retailer=retailer,
            run_status="success",
            quality_status="PASS",
            benchmark_status="PASS",
            benchmark_context=benchmark_context,
            quality_score=99.6,
            metrics_json=json.dumps(metrics),
        )
    )
    db.commit()
    return store


def test_rewe_pass_becomes_collector_primary():
    db = _session()
    store = _ready_store(db)
    target = next(row for row in TARGET_MARKETS if row.key == "rewe-hundertmark-dierdorf")

    result = assess_store_readiness(db, target, store)

    assert result.status == "READY"
    assert result.source_strategy == "collector_primary"
    assert result.quality_status == "PASS"
    assert result.benchmark_status == "PASS"
    assert result.benchmark_context == "PRODUCTION"
    assert result.external_validation_status == "PASS"
    assert result.external_validation_checked == 10
    assert result.quality_score == 99.6
    assert result.offers_imported == 206
    assert result.reasons == ()


def test_quality_pass_without_production_benchmark_keeps_external_primary():
    db = _session()
    store = _ready_store(db)
    snapshot = db.query(CollectionQualitySnapshot).one()
    snapshot.benchmark_status = "NOT_APPLICABLE"
    db.commit()
    target = next(row for row in TARGET_MARKETS if row.key == "rewe-hundertmark-dierdorf")

    result = assess_store_readiness(db, target, store)

    assert result.status == "VALIDATION_REQUIRED"
    assert result.source_strategy == "external_primary"
    assert "benchmark_not_pass" in result.reasons


def test_golden_benchmark_pass_does_not_unlock_production():
    db = _session()
    store = _ready_store(db, benchmark_context="GOLDEN")
    target = next(row for row in TARGET_MARKETS if row.key == "rewe-hundertmark-dierdorf")

    result = assess_store_readiness(db, target, store)

    assert result.source_strategy == "external_primary"
    assert "benchmark_context_not_production" in result.reasons


def test_missing_external_validation_keeps_external_primary():
    db = _session()
    store = _ready_store(db, external_validation=False)
    target = next(row for row in TARGET_MARKETS if row.key == "rewe-hundertmark-dierdorf")

    result = assess_store_readiness(db, target, store)

    assert result.source_strategy == "external_primary"
    assert "external_validation_not_pass" in result.reasons
    assert "external_validation_insufficient_samples" in result.reasons


def test_external_validation_requires_at_least_ten_samples():
    db = _session()
    store = _ready_store(db)
    snapshot = db.query(CollectionQualitySnapshot).one()
    metrics = json.loads(snapshot.metrics_json)
    metrics["external_validation_checked"] = 9
    snapshot.metrics_json = json.dumps(metrics)
    db.commit()
    target = next(row for row in TARGET_MARKETS if row.key == "rewe-hundertmark-dierdorf")

    result = assess_store_readiness(db, target, store)

    assert result.source_strategy == "external_primary"
    assert "external_validation_insufficient_samples" in result.reasons


def test_rewe_external_id_must_match_exactly():
    db = _session()
    _ready_store(db, external_id="wrong-market-id")

    report = build_multi_market_readiness(db)
    rewe = next(row for row in report["stores"] if row["target_key"] == "rewe-hundertmark-dierdorf")

    assert rewe["store_id"] is None
    assert rewe["status"] == "MISSING_STORE"
    assert rewe["source_strategy"] == "external_primary"


def test_readiness_report_always_covers_all_seven_target_markets():
    db = _session()
    _ready_store(db)

    report = build_multi_market_readiness(db)

    assert report["target_count"] == 7
    assert len(report["stores"]) == 7
    assert report["collector_primary"] == 1
    assert report["external_primary"] == 6
    assert report["status"] == "IN_PROGRESS"


def test_inapplicable_rewe_diagnostics_render_as_na_instead_of_zero():
    metrics = {
        "price_anchors_detected": 0,
        "price_anchors_matched": 0,
        "price_anchors_ignored": 0,
        "price_anchors_unmatched": 0,
        "price_anchor_match_rate": 0.0,
        "page_offer_recall": 0.0,
        "pages_with_unmatched_prices": [],
    }

    assert quality_metric_for_display(metrics, "price_anchor_match_rate") is None
    assert quality_metric_for_display(metrics, "page_offer_recall") is None


def test_real_zero_is_preserved_when_diagnostic_is_explicitly_applicable():
    metrics = {
        "price_anchor_match_rate": 0.0,
        "price_anchor_match_rate_applicable": True,
        "page_offer_recall": 0.0,
        "page_offer_recall_applicable": True,
    }

    assert quality_metric_for_display(metrics, "price_anchor_match_rate") == 0.0
    assert quality_metric_for_display(metrics, "page_offer_recall") == 0.0


def test_external_validation_scores_local_offer_fields_and_detects_missing_offer():
    offers = [
        {
            "id": 10,
            "product_name": "Delverde Pasta",
            "brand": "Delverde",
            "package_size": "500 g",
            "price": 0.88,
            "unit_price": 1.76,
            "unit_price_unit": "kg",
            "valid_from": date(2026, 9, 7),
            "valid_to": date(2026, 9, 12),
            "local_store_offer": True,
            "image_present": True,
        }
    ]
    references = [
        ExternalOfferSample(
            product_name="Delverde Pasta",
            brand="Delverde",
            package_size="500 g",
            price=0.88,
            unit_price=1.76,
            unit_price_unit="kg",
            valid_from=date(2026, 9, 7),
            valid_to=date(2026, 9, 12),
            image_expected=True,
        ),
        ExternalOfferSample(product_name="Philadelphia Natur", package_size="195 g", price=1.11),
    ]

    result = validate_external_samples(references, offers, min_samples=1)

    assert result.checked == 2
    assert result.matched == 1
    assert result.missing == 1
    assert result.online_only_leaks == 0
    assert result.status == "FAIL"
    assert result.samples[0].score == 100.0
    assert result.samples[1].mismatches == ("offer_missing",)


def test_external_validation_result_is_persisted_on_exact_run_snapshot():
    db = _session()
    _ready_store(db, external_validation=False)
    run = db.query(CollectionRun).one()
    references = [ExternalOfferSample(product_name=f"Produkt {idx}") for idx in range(10)]
    offers = [{"id": idx, "product_name": f"Produkt {idx}", "local_store_offer": True} for idx in range(10)]
    result = validate_external_samples(references, offers)

    persist_external_validation_result(db, run=run, result=result)

    metrics = json.loads(db.query(CollectionQualitySnapshot).one().metrics_json)
    assert metrics["external_validation_status"] == "PASS"
    assert metrics["external_validation_checked"] == 10
    assert metrics["external_validation_online_only_leaks"] == 0


def test_online_only_reference_is_negative_control_and_leak_fails_validation():
    offers = [{"id": 99, "product_name": "Online Weinpaket", "local_store_offer": True}]
    references = [
        ExternalOfferSample(product_name="Online Weinpaket", online_only=True),
        *[
            ExternalOfferSample(product_name=f"Lokales Produkt {idx}")
            for idx in range(1, 10)
        ],
    ]

    result = validate_external_samples(references, offers)

    assert result.online_only_leaks == 1
    assert result.status == "FAIL"
    assert "online_only_imported" in result.samples[0].mismatches


def test_validation_requires_standard_sample_size():
    references = [ExternalOfferSample(product_name=f"Produkt {idx}") for idx in range(9)]

    result = validate_external_samples(references, [])

    assert result.checked == 9
    assert result.status == "INSUFFICIENT_SAMPLES"


def test_next_week_window_is_always_following_monday_to_sunday():
    assert next_week_window(date(2026, 9, 11)) == (date(2026, 9, 14), date(2026, 9, 20))
    assert next_week_window(date(2026, 9, 14)) == (date(2026, 9, 21), date(2026, 9, 27))
