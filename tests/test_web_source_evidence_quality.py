from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collection_quality import (
    BenchmarkContext,
    RETAILER_QUALITY_POLICIES,
    RetailerQualityPolicy,
    evaluate_collection_quality,
)
from app.db import Base
from app.extractor_adapter import ImportSummary
from app.models import CollectionRun, MasterProduct, MediaAsset, Offer, OfferOccurrence, Store


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_aldi_web_collection(db, *, with_source_text: bool = True):
    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD QA Test",
        postal_code="56269",
        city="Dierdorf",
        address="Teststr. 3",
        active=True,
        benchmark_verified=True,
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    run = CollectionRun(store_id=store.id, source_key="aldi:test:web", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    rows = []
    for idx in range(2):
        product = MasterProduct(
            brand="Test",
            name=f"ALDI Produkt {idx + 1}",
            package_size="500 g",
            normalized_key=f"aldi-produkt-{idx + 1}",
        )
        db.add(product)
        db.flush()
        source_url = (
            "https://www.aldi-sued.de/produkte/wochenangebote/"
            "markenprodukte-im-angebot/k/1588161427299189"
        )
        offer = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=1.99 + idx,
            unit_price=3.98 + idx,
            unit_price_unit="kg",
            valid_from=date(2026, 9, 7),
            valid_to=date(2026, 9, 12),
            local_store_offer=True,
            source_url=source_url,
        )
        db.add(offer)
        db.flush()
        db.add(
            MediaAsset(
                kind="product",
                master_product_id=product.id,
                source_url=f"https://www.aldi-sued.de/image-{idx}.jpg",
                mime_type="image/jpeg",
                is_primary=True,
                active=True,
            )
        )
        db.add(
            OfferOccurrence(
                offer_id=offer.id,
                prospect_page=None,
                occurrence_fingerprint=(str(idx + 1) * 64)[:64],
                detail_text=f"ALDI Produkt {idx + 1} 500 g",
                package_size="500 g",
                unit_price=offer.unit_price,
                unit_price_unit="kg",
                source_text=(f"ALDI Produkt {idx + 1} 500 g 1,99 €" if with_source_text else None),
                source_url=source_url,
            )
        )
        rows.append(
            SimpleNamespace(
                product_name=product.name,
                price=offer.price,
                quantity=500.0,
                unit="g",
                unit_price=offer.unit_price,
                valid_from="07.09.2026",
                valid_to="12.09.2026",
                source_text=f"ALDI Produkt {idx + 1} 500 g",
                source_url=source_url,
                store_name=store.name,
            )
        )
    db.commit()
    return store, run, rows


def test_structured_web_occurrences_are_valid_source_evidence(monkeypatch):
    db = _session()
    store, run, rows = _seed_aldi_web_collection(db)
    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "ALDI SÜD",
        RetailerQualityPolicy(expected_min_offers=2, min_image_rate=20.0),
    )

    quality_status, benchmark_status, score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=ImportSummary(received=2, imported=2),
        images_saved=2,
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert quality_status == "PASS"
    assert benchmark_status == "PASS"
    assert score >= 80.0
    assert metrics["archive_created"] is False
    assert metrics["provenance_rate"] == 0.0
    assert metrics["source_evidence_mode"] == "web_occurrence"
    assert metrics["source_evidence_rate"] == 100.0
    assert metrics["web_evidence_rate"] == 100.0
    assert metrics["quality_reasons"] == []


def test_bare_occurrence_without_source_text_does_not_fake_provenance(monkeypatch):
    db = _session()
    store, run, rows = _seed_aldi_web_collection(db, with_source_text=False)
    monkeypatch.setitem(
        RETAILER_QUALITY_POLICIES,
        "ALDI SÜD",
        RetailerQualityPolicy(expected_min_offers=2, min_image_rate=20.0),
    )

    quality_status, benchmark_status, _score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=ImportSummary(received=2, imported=2),
        images_saved=2,
        benchmark_context=BenchmarkContext.PRODUCTION,
    )

    assert quality_status == "WARN"
    assert benchmark_status == "PASS"
    assert metrics["occurrence_rate"] == 100.0
    assert metrics["source_evidence_rate"] == 0.0
    assert "source_evidence_below_target" in metrics["quality_reasons"]
