from datetime import date
import json
from types import SimpleNamespace

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import collection_service, product_media, prospects
from app.collection_quality import BenchmarkContext, CollectionQualitySnapshot
from app.db import Base
from app.engine_v140.collectors import CollectedOffer
from app.engine_v140.edeka_pdf import (
    EdekaPdfExtraction,
    _cached_extraction,
    _offer_cache_payload,
)
from app.engine_v140.prospect_pdf_engine import PdfParseResult
from app.engine_v140.source_registry import RetailSource
from app.models import MediaAsset, MediaAssetMetadata, Offer, OfferOccurrence, Store
from app.prospect_models import OfferProvenance, ProspectArchive


def _pdf(path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "EDEKA Testprospekt")
    document.save(path)
    document.close()


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_edeka_pdf_archive_offer_occurrence_provenance_and_crop_pipeline(monkeypatch, tmp_path):
    db = _db()
    store = Store(
        retailer="EDEKA",
        name="EDEKA Neuer Markt",
        postal_code="00000",
        city="Test",
        address="Test 1",
        active=True,
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    data_dir = tmp_path / "data"
    pdf_path = data_dir / "prospects" / "edeka" / "kw34.pdf"
    pdf_path.parent.mkdir(parents=True)
    _pdf(pdf_path)
    crop = data_dir / "diagnostics" / "edeka" / "sha" / "crops" / "p01.jpg"
    crop.parent.mkdir(parents=True)
    crop.write_bytes(b"edeka-audit-crop")
    monkeypatch.setattr(product_media, "settings", SimpleNamespace(data_dir=data_dir))

    market_url = "https://www.edeka.de/maerkte/999999/angebote/"
    pdf_url = "https://media.example.test/flyers/999999/pdf"
    prospects.save_prospect(
        db,
        store,
        period_key="current",
        source_url=market_url,
        pdf_url=pdf_url,
        pdf_path=pdf_path,
        valid_from=date(2026, 8, 17),
        valid_to=date(2026, 8, 23),
    )
    row = CollectedOffer(
        source_key="auto_edeka_1",
        store_name=store.name,
        retailer="EDEKA",
        product_name="Bertolli Olivenöl",
        category="Sonstiges",
        price=5.99,
        regular_price=7.99,
        quantity=500,
        unit="ml",
        unit_price=11.98,
        unit_price_unit="l",
        valid_from="17.08.2026",
        valid_to="23.08.2026",
        source_text="PDF Seite 1: EDEKA OCR bbox=(1, 2, 3, 4)",
        source_url=pdf_url,
        local_store_offer=True,
        confidence=0.97,
    )
    row.audit_image_path = str(crop)
    row.image_media_source = "prospect_crop"
    parsed = PdfParseResult(
        "EDEKA",
        1,
        1,
        [row],
        date(2026, 8, 17),
        date(2026, 8, 23),
        None,
        ["EDEKA PDF layout parser"],
        ocr_pages=[1],
        price_anchors_detected=1,
        price_anchors_matched=1,
        page_offer_recall=100.0,
    )
    monkeypatch.setattr(collection_service, "parse_pdf_file", lambda source, path: parsed)

    _, summary, run = collection_service.collect_pdf_for_store(
        db,
        store.name,
        pdf_path,
        benchmark_context=BenchmarkContext.NOT_APPLICABLE,
    )

    assert summary.imported == 1
    assert run.status == "success"
    assert db.query(Offer).count() == 1
    assert db.query(ProspectArchive).one().pdf_sha256
    assert db.query(OfferOccurrence).one().prospect_page == 1
    assert db.query(OfferProvenance).one().prospect_page == 1
    asset = db.query(MediaAsset).one()
    assert db.query(MediaAssetMetadata).filter_by(media_asset_id=asset.id).one().media_source == "prospect_crop"
    snapshot = db.query(CollectionQualitySnapshot).one()
    metrics = json.loads(snapshot.metrics_json)
    assert snapshot.run_status == "success"
    assert snapshot.quality_status == "PASS"
    assert snapshot.benchmark_status == "NOT_APPLICABLE"
    assert metrics["provenance_rate"] == 100.0
    assert metrics["occurrence_rate"] == 100.0


def test_edeka_extraction_cache_rebinds_same_pdf_result_to_another_market(tmp_path):
    crop = tmp_path / "crop.jpg"
    crop.write_bytes(b"crop")
    source_a = RetailSource("edeka_a", "EDEKA", "EDEKA Markt A", "https://example.test/a", "prospect_discovery", "store_specific")
    source_b = RetailSource("edeka_b", "EDEKA", "EDEKA Markt B", "https://example.test/b", "prospect_discovery", "store_specific")
    row = CollectedOffer(
        source_a.key,
        source_a.store_name,
        source_a.retailer,
        "Tafeläpfel SweeTango",
        "Sonstiges",
        1.99,
        quantity=1,
        unit="kg",
        source_text="PDF Seite 3: OCR",
        source_url=source_a.url,
    )
    row.audit_image_path = str(crop)
    row.image_media_source = "prospect_crop"
    diagnostics = tmp_path / "analysis.json"
    diagnostics.write_text("{}", encoding="utf-8")
    cache = tmp_path / "extraction-v1.json"
    cache.write_text(
        json.dumps({
            "cache_version": 1,
            "pdf_sha256": "abc",
            "page_count": 26,
            "native_text_pages": [24, 25],
            "ocr_pages": list(range(1, 24)) + [26],
            "price_anchors_detected": 1,
            "price_anchors_matched": 1,
            "price_anchors_ignored": 0,
            "price_anchors_unmatched": 0,
            "pages_with_unmatched_prices": [],
            "page_offer_recall": 100.0,
            "offers": [_offer_cache_payload(row)],
            "notes": ["first market"],
        }),
        encoding="utf-8",
    )

    result = _cached_extraction(
        source_b,
        cache,
        digest="abc",
        source_url=source_b.url,
        diagnostics_path=diagnostics,
    )

    assert isinstance(result, EdekaPdfExtraction)
    assert result.offers[0].source_key == source_b.key
    assert result.offers[0].store_name == source_b.store_name
    assert result.offers[0].source_url == source_b.url
    assert result.offers[0].audit_image_path == str(crop)
    assert result.page_offer_recall == 100.0
    assert result.notes[-1] == "EDEKA extraction reused by pdf_sha256"
