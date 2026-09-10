from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import MasterProduct, Offer, ProductBarcode, Store
from app.offer_accuracy import build_offer_accuracy_scorecard
from app.web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun
from app.web_offer_audit_runtime import period_bounds


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def _store(db, name="REWE Accuracy Test"):
    row = Store(
        retailer="REWE",
        name=name,
        postal_code="56269",
        city="Dierdorf",
        address="Teststraße 1",
        active=True,
        benchmark_verified=True,
        external_id="rewe-test",
        source_url="https://www.rewe.de/marktseite/test",
    )
    db.add(row)
    db.flush()
    return row


def _run(db, store):
    row = WebOfferAuditRun(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        source_url=store.source_url,
        collector_path="rewe-web-audit",
        status="success",
    )
    db.add(row)
    db.flush()
    return row


def _product_offer(db, store, *, name="Coca-Cola", package_size="1,5 l", price=1.29, barcode="4000000000001"):
    start, end = period_bounds("current")
    product = MasterProduct(name=name, package_size=package_size, normalized_key=f"br2-{barcode}")
    db.add(product)
    db.flush()
    db.add(ProductBarcode(barcode=barcode, master_product_id=product.id, source="test"))
    db.add(Offer(
        store_id=store.id,
        master_product_id=product.id,
        price=price,
        valid_from=start,
        valid_to=end,
        local_store_offer=True,
        source_url=store.source_url,
    ))
    db.flush()
    return product


def _source_item(db, run, store, *, name="Coca-Cola", price=1.29, barcode="4000000000001", valid_from=None, valid_to=None):
    start, end = period_bounds("current")
    row = WebOfferAuditItem(
        run_id=run.id,
        store_id=store.id,
        retailer="REWE",
        source_type="web",
        source_url=store.source_url or "https://www.rewe.de/",
        ean=barcode,
        name=name,
        price=price,
        quantity="1,5 l",
        quantity_value=1.5,
        quantity_unit="l",
        packaging_text="1,5 l",
        valid_from=valid_from if valid_from is not None else start,
        valid_to=valid_to if valid_to is not None else end,
        valid=True,
        dedupe_key=f"ean:{barcode}:{name}",
    )
    db.add(row)
    db.flush()
    return row


def test_perfect_rewe_store_is_beta_ready():
    db = _db()
    store = _store(db)
    run = _run(db, store)
    _product_offer(db, store)
    _source_item(db, run, store)
    db.commit()
    db.refresh(run)

    score = build_offer_accuracy_scorecard(db, run)

    assert score["accuracy_source_count"] == 1
    assert score["accuracy_production_count"] == 1
    assert score["accuracy_matched"] == 1
    assert score["accuracy_completeness_pct"] == 100.0
    assert score["accuracy_source_capture_pct"] == 100.0
    assert score["accuracy_production_capture_pct"] == 100.0
    assert score["accuracy_price_accuracy_pct"] == 100.0
    assert score["accuracy_validity_accuracy_pct"] == 100.0
    assert score["accuracy_exact_pct"] == 100.0
    assert score["accuracy_production_only_provenance"] == "–"
    assert score["accuracy_production_duplicate_provenance"] == "–"
    assert score["accuracy_beta_ready"] is True
    db.close()


def test_price_and_validity_mismatch_fail_beta_gate_without_mutating_offer():
    from datetime import timedelta

    db = _db()
    store = _store(db, "REWE Mismatch Test")
    run = _run(db, store)
    _product_offer(db, store, price=1.29)
    start, end = period_bounds("current")
    _source_item(db, run, store, price=1.49, valid_from=start + timedelta(days=1), valid_to=end)
    db.commit()
    db.refresh(run)

    score = build_offer_accuracy_scorecard(db, run)

    assert score["accuracy_matched"] == 1
    assert score["accuracy_price_mismatch"] == 1
    assert score["accuracy_validity_mismatch"] == 1
    assert score["accuracy_price_accuracy_pct"] == 0.0
    assert score["accuracy_validity_accuracy_pct"] == 0.0
    assert score["accuracy_beta_ready"] is False
    assert db.query(Offer).one().price == 1.29
    db.close()


def test_source_only_offer_reduces_completeness():
    db = _db()
    store = _store(db, "REWE Completeness Test")
    run = _run(db, store)
    _product_offer(db, store)
    _source_item(db, run, store)
    _source_item(db, run, store, name="Nur in Händlerquelle", price=2.49, barcode="4000000000002")
    db.commit()
    db.refresh(run)

    score = build_offer_accuracy_scorecard(db, run)

    assert score["accuracy_source_count"] == 2
    assert score["accuracy_matched"] == 1
    assert score["accuracy_source_only"] == 1
    assert score["accuracy_completeness_pct"] == 50.0
    assert score["accuracy_beta_ready"] is False
    db.close()


def test_wrong_store_source_evidence_is_explicitly_rejected_from_accuracy_denominator():
    db = _db()
    store = _store(db, "REWE Market Context A")
    other = _store(db, "REWE Market Context B")
    run = _run(db, store)
    _product_offer(db, store)
    _source_item(db, run, other)
    db.commit()
    db.refresh(run)

    score = build_offer_accuracy_scorecard(db, run)

    assert score["accuracy_market_context_mismatch"] == 1
    assert score["accuracy_source_count"] == 0
    assert score["accuracy_beta_ready"] is False
    db.close()


def test_production_offer_on_same_official_store_alias_matches_canonical_audit():
    db = _db()
    legacy = Store(
        retailer="REWE",
        name="REWE Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
        source_url=None,
    )
    canonical = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Straße 20 - 22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
        source_url="https://www.rewe.de/marktseite/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
    )
    db.add_all([legacy, canonical])
    db.flush()
    run = _run(db, canonical)
    _product_offer(db, legacy)
    _source_item(db, run, canonical)
    db.commit()
    db.refresh(run)

    score = build_offer_accuracy_scorecard(db, run)

    assert score["accuracy_production_count"] == 1
    assert score["accuracy_matched"] == 1
    assert score["accuracy_source_only"] == 0
    assert score["accuracy_beta_ready"] is True
    db.close()


def test_truncated_retailer_audit_cannot_report_full_completeness():
    db = _db()
    store = _store(db, "REWE Truncated Audit")
    run = _run(db, store)
    _product_offer(db, store, name="Matched", barcode="4000000000101")
    _source_item(db, run, store, name="Matched", barcode="4000000000101")
    _product_offer(db, store, name="Production only", barcode="4000000000102")
    db.commit()
    db.refresh(run)

    score = build_offer_accuracy_scorecard(db, run)

    assert score["accuracy_source_count"] == 1
    assert score["accuracy_production_count"] == 2
    assert score["accuracy_matched"] == 1
    assert score["accuracy_source_only"] == 0
    assert score["accuracy_production_only"] == 1
    assert score["accuracy_source_capture_pct"] == 100.0
    assert score["accuracy_production_capture_pct"] == 50.0
    assert score["accuracy_completeness_pct"] == 50.0
    assert score["accuracy_exact_pct"] == 50.0
    assert "Production only" in score["accuracy_production_only_provenance"]
    assert "ohne Prospekt-Provenienz" in score["accuracy_production_only_provenance"]
    assert score["accuracy_beta_ready"] is False
    db.close()
