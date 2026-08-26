import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collection_quality import CollectionQualitySnapshot
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base
from app.market_activation import (
    StoreActivationState,
    StoreQualityAssessment,
    assess_latest_store_quality,
    begin_test_scrape,
    complete_test_scrape,
    publish_store,
    reactivate_store,
    register_promoted_store,
    store_is_public,
    store_ready_for_publication,
    suspend_store,
)
from app.models import CollectionRun, Store


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _store(db, *, public=False):
    store = Store(
        retailer="Test", name=f"Testmarkt {id(db)}", postal_code="56305",
        city="Puderbach", address="Marktweg 1", latitude=50.6, longitude=7.6,
        active=True, benchmark_verified=public,
    )
    db.add(store)
    db.commit()
    return store


def _promote(db, store):
    candidate = StoreDiscoveryCandidate(
        discovery_key=f"test:{store.id}",
        retailer=store.retailer, name=store.name, postal_code=store.postal_code,
        city=store.city, address=store.address, latitude=store.latitude,
        longitude=store.longitude, source="official:test", status="promoted",
        matched_store_id=store.id, address_verified=True, coordinates_verified=True,
        official_source_verified=True,
    )
    db.add(candidate)
    db.flush()
    register_promoted_store(db, store, candidate)
    db.commit()
    return candidate


def _run(db, store, *, status="success", valid=12, raw=12, priced=11, duplicates=0, invalid=0):
    now = datetime.utcnow()
    run = CollectionRun(
        store_id=store.id, source_key="test:collector", started_at=now - timedelta(seconds=4),
        finished_at=now, status=status, offers_received=raw, offers_imported=valid,
        message=None if status == "success" else "collector failed",
    )
    db.add(run)
    db.flush()
    snapshot = CollectionQualitySnapshot(
        run_id=run.id, store_id=store.id, retailer=store.retailer, run_status=status,
        quality_status="PASS" if status == "success" else "FAIL",
        benchmark_status="NOT_APPLICABLE", benchmark_context="not_applicable",
        quality_score=90, metrics_json=json.dumps({
            "raw_offer_count": raw, "eligible_offer_count": raw - invalid,
            "valid_offer_count": valid, "offers_with_price": priced,
            "offers_with_unit_or_base_price": 8, "duplicate_count": duplicates,
            "invalid_or_non_product_count": invalid, "prospect_date_available": True,
            "prospect_page_available": True,
        }),
    )
    db.add(snapshot)
    db.commit()
    return run


def _test_scrape(db, store, **metrics):
    begin_test_scrape(db, store)
    run = _run(db, store, **metrics)
    complete_test_scrape(db, store, run)
    return run


def test_test_scrape_requires_verified_promotion_and_promotion_is_not_public():
    db = _db(); store = _store(db)
    with pytest.raises(ValueError):
        begin_test_scrape(db, store)
    _promote(db, store)
    begin_test_scrape(db, store)
    assert store.benchmark_verified is False
    assert not store_is_public(store)
    db.close()


@pytest.mark.parametrize(
    "metrics,failed_check",
    [
        ({"status": "failed"}, "scrape_success"),
        ({"valid": 9, "priced": 9}, "valid_offer_count"),
        ({"valid": 12, "priced": 9}, "price_coverage"),
        ({"raw": 20, "valid": 18, "priced": 18, "duplicates": 3}, "duplicate_rate"),
        ({"raw": 20, "valid": 15, "priced": 15, "invalid": 5}, "invalid_or_non_product_rate"),
    ],
)
def test_quality_gate_rejects_each_objective_failure(metrics, failed_check):
    db = _db(); store = _store(db); _promote(db, store); _test_scrape(db, store, **metrics)
    result = assess_latest_store_quality(db, store)
    assert not result.passed
    assert result.checks[failed_check] is False
    assert store.benchmark_verified is False
    assert not store_ready_for_publication(db, store)
    db.close()


def test_quality_pass_needs_explicit_publish_and_publish_requires_full_gate():
    db = _db(); store = _store(db); _promote(db, store); _test_scrape(db, store)
    result = assess_latest_store_quality(db, store)
    assert result.passed and result.score == 100
    assert store.benchmark_verified is False
    assert store_ready_for_publication(db, store, result)
    publish_store(db, store)
    assert store_is_public(store)
    assert db.query(StoreActivationState).filter_by(store_id=store.id).one().lifecycle_status == "public"
    db.close()


def test_suspend_hides_store_preserves_history_and_reactivation_requires_publish():
    db = _db(); store = _store(db); _promote(db, store); run = _test_scrape(db, store)
    assess_latest_store_quality(db, store); publish_store(db, store)
    assessment_count = db.query(StoreQualityAssessment).filter_by(store_id=store.id).count()
    suspend_store(db, store, "Quelle defekt")
    assert not store_is_public(store) and db.get(CollectionRun, run.id) is not None
    assert db.query(StoreQualityAssessment).filter_by(store_id=store.id).count() == assessment_count
    reactivate_store(db, store)
    assert not store_is_public(store)
    assert store_ready_for_publication(db, store)
    db.close()


def test_failed_publication_never_changes_benchmark_flag():
    db = _db(); store = _store(db); _promote(db, store)
    with pytest.raises(ValueError):
        publish_store(db, store)
    assert store.benchmark_verified is False
    db.close()
