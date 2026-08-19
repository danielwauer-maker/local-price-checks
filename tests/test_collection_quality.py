from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collection_quality import (
    CollectionQualitySnapshot,
    RetailerQualityPolicy,
    RETAILER_QUALITY_POLICIES,
    evaluate_collection_quality,
    persist_collection_quality,
)
from app.db import Base
from app.extractor_adapter import ImportSummary
from app.models import CollectionRun, MasterProduct, MediaAsset, Offer, OfferOccurrence, Store
from app.prospect_models import OfferProvenance, ProspectArchive


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_complete_rewe(db):
    store = Store(
        retailer="REWE",
        name="REWE QA Test",
        postal_code="56269",
        city="Dierdorf",
        address="Teststr. 1",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    run = CollectionRun(store_id=store.id, source_key="rewe:test", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    archive = ProspectArchive(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        valid_from=date(2026, 8, 17),
        valid_to=date(2026, 8, 22),
        source_url="https://example.invalid/rewe",
        pdf_url="web-snapshot://test",
        original_filename="rewe.pdf",
        local_path="/tmp/rewe.pdf",
        page_count=2,
        pdf_sha256="a" * 64,
        pdf_bytes=b"%PDF-test",
    )
    db.add(archive)
    db.commit()
    db.refresh(archive)

    rows = []
    for idx in range(2):
        product = MasterProduct(
            brand="Test",
            name=f"Test Produkt {idx + 1}",
            package_size="500 g",
            normalized_key=f"test-produkt-{idx + 1}",
        )
        db.add(product)
        db.flush()
        offer = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=1.99 + idx,
            unit_price=3.98 + idx,
            unit_price_unit="kg",
            valid_from=date(2026, 8, 17),
            valid_to=date(2026, 8, 22),
            local_store_offer=True,
        )
        db.add(offer)
        db.flush()
        db.add(MediaAsset(
            kind="product",
            master_product_id=product.id,
            file_path=f"/tmp/p{idx}.jpg",
            mime_type="image/jpeg",
            is_primary=True,
            active=True,
        ))
        db.add(OfferProvenance(
            offer_id=offer.id,
            prospect_archive_id=archive.id,
            prospect_page=idx + 1,
        ))
        db.add(OfferOccurrence(
            offer_id=offer.id,
            prospect_page=idx + 1,
            occurrence_fingerprint=(str(idx + 1) * 64)[:64],
            package_size="500 g",
            unit_price=offer.unit_price,
            unit_price_unit="kg",
        ))
        rows.append(SimpleNamespace(product_name=product.name))
    db.commit()
    return store, run, rows


def test_complete_collection_can_pass_with_retailer_policy(monkeypatch):
    db = _session()
    store, run, rows = _seed_complete_rewe(db)
    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "REWE",
        RetailerQualityPolicy(
            expected_min_offers=2,
            pass_count_ratio=0.8,
            fail_count_ratio=0.3,
            min_import_rate=80.0,
            min_provenance_rate=95.0,
            min_package_rate=45.0,
            min_image_rate=50.0,
        ),
    )
    summary = ImportSummary(received=2, imported=2)

    status, score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=summary,
        images_saved=2,
    )

    assert status == "PASS"
    assert score >= 85.0
    assert metrics["archive_created"] is True
    assert metrics["provenance_rate"] == 100.0
    assert metrics["image_rate"] == 100.0
    assert metrics["package_rate"] == 100.0
    assert metrics["unit_price_rate"] == 100.0


def test_missing_archive_and_far_too_few_offers_fail_quality(monkeypatch):
    db = _session()
    store = Store(
        retailer="Lidl",
        name="Lidl QA Test",
        postal_code="57610",
        city="Puderbach",
        address="Teststr. 2",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    run = CollectionRun(store_id=store.id, source_key="lidl:test", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "Lidl",
        RetailerQualityPolicy(expected_min_offers=100),
    )
    summary = ImportSummary(received=10, imported=10)
    rows = [SimpleNamespace(product_name=f"Produkt {i}") for i in range(10)]

    diagnostic, metrics = persist_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=summary,
        images_saved=0,
    )

    assert metrics["qa_status"] == "FAIL"
    assert "offer_count_far_below_baseline" in metrics["reasons"]
    assert "archive_missing" in metrics["reasons"]
    assert "qa_status=FAIL" in diagnostic
    snapshot = db.query(CollectionQualitySnapshot).filter_by(run_id=run.id).one()
    assert snapshot.qa_status == "FAIL"
