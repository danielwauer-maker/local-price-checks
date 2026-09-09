import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.collection_quality import CollectionQualitySnapshot
from app.data_operations import build_data_operations
from app.db import Base
from app.models import CollectionRun, MasterProduct, Offer, Store


def test_data_operations_kpis_critical_first_and_bounded_queries():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    failed = Store(retailer="REWE", name="Failed", postal_code="1", city="A", address="A", active=True, benchmark_verified=True)
    healthy = Store(retailer="EDEKA", name="Healthy", postal_code="2", city="B", address="B", active=True, benchmark_verified=True)
    db.add_all([failed, healthy]); db.flush()
    bad_run = CollectionRun(store_id=failed.id, source_key="bad", status="blocked", offers_received=21, message="offer_count_collapse")
    good_run = CollectionRun(store_id=healthy.id, source_key="good", status="success", offers_received=1, offers_imported=1)
    db.add_all([bad_run, good_run]); db.flush()
    product = MasterProduct(name="Produkt", normalized_key="br1a-dashboard")
    db.add(product); db.flush()
    business_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
    db.add(Offer(store_id=healthy.id, master_product_id=product.id, price=1.99, valid_from=business_date, valid_to=business_date, local_store_offer=True))
    db.add_all([
        CollectionQualitySnapshot(run_id=bad_run.id, store_id=failed.id, retailer="REWE", run_status="blocked", quality_status="FAIL", benchmark_status="FAIL", benchmark_context="PRODUCTION", quality_score=0, metrics_json=json.dumps({"import_rate": 0})),
        CollectionQualitySnapshot(run_id=good_run.id, store_id=healthy.id, retailer="EDEKA", run_status="success", quality_status="PASS", benchmark_status="PASS", benchmark_context="PRODUCTION", quality_score=90, metrics_json=json.dumps({"import_rate": 100})),
    ])
    db.commit()
    counter = {"queries": 0}
    event.listen(engine, "before_cursor_execute", lambda *_: counter.__setitem__("queries", counter["queries"] + 1))
    result = build_data_operations(db, stale_after_hours=36)
    assert result["kpis"]["total"] == 2
    assert result["kpis"]["blocked_failed"] == 1
    assert result["kpis"]["active_offers"] == 1
    assert result["attention"][0]["severity"] == "critical"
    assert result["attention"][0]["url"].startswith("/admin/collector")
    assert next(row for row in result["markets"] if row["store"].name == "Healthy")["state"] == "current"
    assert counter["queries"] <= 12
