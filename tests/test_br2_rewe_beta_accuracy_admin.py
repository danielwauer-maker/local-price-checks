from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_web_offer_audit_routes import _rewe_beta_market_statuses
from app.db import Base
from app.models import MasterProduct, Offer, Store
from app.web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun
from app.web_offer_audit_runtime import period_bounds


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _store(db, name, *, retailer="REWE", verified=True, active=True):
    row = Store(
        retailer=retailer,
        name=name,
        postal_code="56269",
        city="Dierdorf",
        address=f"{name} 1",
        active=active,
        benchmark_verified=verified,
        external_id=f"id-{name}",
        source_url="https://www.rewe.de/marktseite/test",
    )
    db.add(row)
    db.flush()
    return row


def _perfect_run(db, store):
    start, end = period_bounds("current")
    product = MasterProduct(name="Milch", package_size="1 l", normalized_key=f"milk-{store.id}")
    db.add(product)
    db.flush()
    db.add(Offer(
        store_id=store.id,
        master_product_id=product.id,
        price=1.19,
        valid_from=start,
        valid_to=end,
        local_store_offer=True,
        source_url=store.source_url,
    ))
    run = WebOfferAuditRun(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        source_url=store.source_url,
        collector_path="rewe-web-audit",
        status="success",
    )
    db.add(run)
    db.flush()
    db.add(WebOfferAuditItem(
        run_id=run.id,
        store_id=store.id,
        retailer="REWE",
        source_type="web",
        source_url=store.source_url,
        name="Milch",
        price=1.19,
        quantity="1 l",
        quantity_value=1.0,
        quantity_unit="l",
        packaging_text="1 l",
        valid_from=start,
        valid_to=end,
        valid=True,
        dedupe_key=f"milk-{store.id}",
    ))
    db.flush()
    return run


def test_rewe_beta_statuses_include_only_active_verified_rewe_and_score_latest_run():
    db = _db()
    ready = _store(db, "REWE Ready")
    pending = _store(db, "REWE Pending")
    _store(db, "REWE Unverified", verified=False)
    _store(db, "REWE Inactive", active=False)
    _store(db, "EDEKA Verified", retailer="EDEKA")
    _perfect_run(db, ready)
    db.commit()

    rows = _rewe_beta_market_statuses(db)

    assert [row["store"].name for row in rows] == ["REWE Pending", "REWE Ready"]
    by_name = {row["store"].name: row for row in rows}
    assert by_name["REWE Ready"]["state"] == "beta_ready"
    assert by_name["REWE Ready"]["scorecard"]["accuracy_beta_ready"] is True
    assert by_name["REWE Pending"]["state"] == "not_audited"
    db.close()


def test_rewe_beta_status_uses_latest_current_run_and_surfaces_failure():
    db = _db()
    store = _store(db, "REWE Latest")
    _perfect_run(db, store)
    failed = WebOfferAuditRun(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        source_url=store.source_url,
        collector_path="rewe-web-audit",
        status="failed",
        error_type="blocked",
        message="blocked",
    )
    db.add(failed)
    db.commit()

    row = _rewe_beta_market_statuses(db)[0]

    assert row["run"].id == failed.id
    assert row["state"] == "audit_failed"
    assert row["scorecard"] == {}
    db.close()
