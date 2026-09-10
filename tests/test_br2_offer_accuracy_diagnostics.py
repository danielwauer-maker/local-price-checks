from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import MasterProduct, Offer, Store
from app.offer_accuracy import build_offer_accuracy_scorecard
from app.web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun
from app.web_offer_audit_runtime import period_bounds


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_scorecard_names_source_only_production_only_and_duplicate_candidates():
    db = _db()
    store = Store(
        retailer="REWE",
        name="REWE Diagnose",
        postal_code="56269",
        city="Dierdorf",
        address="Test 1",
        active=True,
        benchmark_verified=True,
        external_id="diag-1",
        source_url="https://www.rewe.de/marktseite/test",
    )
    db.add(store)
    db.flush()
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
    start, end = period_bounds("current")

    matched = MasterProduct(name="Matched", package_size="1 l", normalized_key="diag-matched")
    prod_only = MasterProduct(name="Nur Produktion", package_size="500 g", normalized_key="diag-prod-only")
    duplicate_a = MasterProduct(name="Doppelartikel", package_size="250 g", normalized_key="diag-dup-a")
    duplicate_b = MasterProduct(name="Doppelartikel", package_size="250 g", normalized_key="diag-dup-b")
    db.add_all([matched, prod_only, duplicate_a, duplicate_b])
    db.flush()
    for product, price in ((matched, 1.29), (prod_only, 2.49), (duplicate_a, 3.49), (duplicate_b, 3.49)):
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

    db.add_all([
        WebOfferAuditItem(
            run_id=run.id, store_id=store.id, retailer="REWE", source_type="web",
            source_url=store.source_url, name="Matched", price=1.29,
            quantity="1 l", quantity_value=1.0, quantity_unit="l", packaging_text="1 l",
            valid_from=start, valid_to=end, valid=True, dedupe_key="matched",
        ),
        WebOfferAuditItem(
            run_id=run.id, store_id=store.id, retailer="REWE", source_type="web",
            source_url=store.source_url, name="Nur Quelle", price=1.99,
            quantity="100 g", quantity_value=100.0, quantity_unit="g", packaging_text="100 g",
            valid_from=start, valid_to=end, valid=True, dedupe_key="source-only",
        ),
    ])
    db.commit()
    db.refresh(run)

    score = build_offer_accuracy_scorecard(db, run)

    assert score["accuracy_source_only"] == 1
    assert "Nur Quelle" in score["accuracy_source_only_examples"]
    assert score["accuracy_production_only"] == 3
    assert "Nur Produktion" in score["accuracy_production_only_examples"]
    assert score["accuracy_production_duplicate_products"] == 1
    assert "Doppelartikel" in score["accuracy_production_duplicate_examples"]
    db.close()
