from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collection_quality import (
    BenchmarkContext,
    CollectionQualitySnapshot,
    RetailerQualityPolicy,
    RETAILER_QUALITY_POLICIES,
    evaluate_collection_quality,
    persist_collection_quality,
)
from app.db import Base
from app.extractor_adapter import ImportSummary
from app.models import CollectionRun, MasterProduct, MediaAsset, MediaAssetMetadata, Offer, OfferOccurrence, Store
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

    quality_status, benchmark_status, score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=summary,
        images_saved=2,
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert quality_status == "PASS"
    assert benchmark_status == "PASS"
    assert score >= 80.0
    assert metrics["archive_created"] is True
    assert metrics["provenance_rate"] == 100.0
    assert metrics["image_rate"] == 100.0
    assert metrics["package_rate"] == 100.0
    assert metrics["unit_price_rate"] == 100.0


def test_single_known_invalid_name_remains_a_quality_warning(monkeypatch):
    db = _session()
    store, run, rows = _seed_complete_rewe(db)
    malformed = db.query(MasterProduct).order_by(MasterProduct.id).first()
    malformed.name = "aus Rind- und Schweinefleisch, mit Käse"
    db.commit()
    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "REWE",
        RetailerQualityPolicy(expected_min_offers=2, min_image_rate=50.0),
    )

    quality_status, _benchmark_status, _score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=ImportSummary(received=2, imported=2),
        images_saved=2,
    )

    assert quality_status == "WARN"
    assert metrics["suspicious_name_count"] == 1
    assert metrics["suspicious_names"] == [{
        "product_id": malformed.id,
        "product_name": "aus Rind- und Schweinefleisch, mit Käse",
        "reason": "Herkunfts-/Beschreibungsfragment statt Produktname",
    }]
    assert "suspicious_product_names" in metrics["quality_reasons"]


def test_small_production_run_fails_benchmark_without_changing_quality_semantics(monkeypatch):
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
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert metrics["quality_status"] == "WARN"
    assert metrics["benchmark_status"] == "FAIL"
    assert "offer_count_far_below_baseline" in metrics["benchmark_reasons"]
    assert "benchmark_status=FAIL" in diagnostic
    snapshot = db.query(CollectionQualitySnapshot).filter_by(run_id=run.id).one()
    assert snapshot.quality_status == "WARN"
    assert snapshot.benchmark_status == "FAIL"


def test_small_synthetic_run_does_not_apply_absolute_retailer_benchmark(monkeypatch):
    db = _session()
    store, run, rows = _seed_complete_rewe(db)
    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "REWE",
        RetailerQualityPolicy(expected_min_offers=180, min_image_rate=50.0),
    )
    summary = ImportSummary(received=2, imported=2)

    diagnostic, metrics = persist_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows[:1],
        summary=ImportSummary(received=1, imported=1),
        images_saved=1,
        run_status="success",
    )

    assert metrics["run_status"] == "success"
    assert metrics["benchmark_status"] == "NOT_APPLICABLE"
    assert "run_status=success" in diagnostic
    assert "benchmark_status=NOT_APPLICABLE" in diagnostic


def test_online_rejections_do_not_reduce_local_import_quality(monkeypatch):
    db = _session()
    store, run, rows = _seed_complete_rewe(db)
    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "REWE",
        RetailerQualityPolicy(expected_min_offers=2, min_image_rate=50.0),
    )
    summary = ImportSummary(received=202, imported=2, rejected_online=200)

    quality_status, _benchmark_status, _score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=[*rows, *[SimpleNamespace(product_name="Shop") for _ in range(200)]],
        summary=summary,
        images_saved=2,
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert quality_status == "PASS"
    assert metrics["offers_received"] == 202
    assert metrics["eligible_offers_received"] == 2
    assert metrics["online_rejected"] == 200
    assert metrics["import_rate"] == 100.0


def test_crop_only_coverage_is_reported_but_weighted_below_official_media(monkeypatch):
    db = _session()
    store, run, rows = _seed_complete_rewe(db)
    for asset in db.query(MediaAsset).all():
        asset.source_url = f"prospect-crop:{asset.id}"
        db.add(MediaAssetMetadata(
            media_asset_id=asset.id,
            media_source="prospect_crop",
            priority=100,
            audit_relevant=True,
        ))
    rows[0].lidl_availability = "LOCAL_ONLY"
    rows[1].lidl_availability = "LOCAL_AND_ONLINE"
    db.commit()
    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "REWE",
        RetailerQualityPolicy(expected_min_offers=2, min_image_rate=50.0),
    )

    quality_status, _benchmark_status, score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=ImportSummary(received=2, imported=2),
        images_saved=2,
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert quality_status == "PASS"
    assert metrics["image_rate"] == 100.0
    assert metrics["official_image_rate"] == 0.0
    assert metrics["crop_fallback_rate"] == 100.0
    assert metrics["weighted_image_rate"] == 50.0
    assert metrics["local_only"] == 1
    assert metrics["local_and_online"] == 1
    assert score < 100.0
