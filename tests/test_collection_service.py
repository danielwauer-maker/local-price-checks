from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.collection_quality import CollectionQualitySnapshot
from app.models import CollectionRun, Offer, Store
from app.engine_v140.collectors import CollectedOffer
from app.engine_v140.prospect_pdf_engine import PdfParseResult
import app.collection_service as service


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def _store(db):
    store = Store(
        retailer="REWE", name="REWE:XL Hundertmark", postal_code="56269",
        city="Dierdorf", address="Königsberger Str. 20-22", benchmark_verified=True,
    )
    db.add(store); db.commit(); db.refresh(store)
    return store


def test_collection_pipeline_records_success(monkeypatch, tmp_path):
    db = _db(); store = _store(db)
    row = CollectedOffer(
        source_key="rewe_dierdorf", store_name=store.name, retailer="REWE",
        product_name="Freixenet Sekt", category="Wein & Sekt", price=3.79,
        quantity=.75, unit="l", unit_price=5.05, unit_price_unit="l",
        valid_from="10.08.2026", valid_to="15.08.2026",
        source_text="Knaller Produktkarte", source_url="https://www.rewe.de/angebote/dierdorf/321019/x/",
        local_store_offer=True, confidence=.99,
    )
    parsed = PdfParseResult("REWE", 1, 100, [row], date(2026,8,10), date(2026,8,15), "321019", ["ok"])
    monkeypatch.setattr(service, "parse_pdf_file", lambda source, path: parsed)
    pdf = tmp_path / "test.pdf"; pdf.write_bytes(b"x")

    _, summary, run = service.collect_pdf_for_store(db, store.name, pdf)
    assert summary.imported == 1
    assert run.status == "success"
    assert run.offers_received == 1
    assert run.offers_imported == 1
    assert db.query(Offer).count() == 1
    snapshot = db.query(CollectionQualitySnapshot).one()
    assert snapshot.run_status == "success"
    assert snapshot.benchmark_status == "NOT_APPLICABLE"


def test_collection_pipeline_records_failure(monkeypatch, tmp_path):
    db = _db(); store = _store(db)
    monkeypatch.setattr(service, "parse_pdf_file", lambda source, path: (_ for _ in ()).throw(RuntimeError("kaputt")))
    pdf = tmp_path / "test.pdf"; pdf.write_bytes(b"x")
    try:
        service.collect_pdf_for_store(db, store.name, pdf)
        assert False, "expected exception"
    except RuntimeError:
        pass
    run = db.query(CollectionRun).one()
    assert run.status == "failed"
    assert "kaputt" in (run.message or "")


def test_partial_collector_timeout_with_imports_is_warning():
    db = _db(); store = _store(db)
    row = CollectedOffer(
        source_key="rewe_dierdorf", store_name=store.name, retailer="REWE",
        product_name="Teilresultat Kaffee 1 kg", category="Kaffee", price=9.99,
        quantity=1, unit="kg", unit_price=9.99, unit_price_unit="kg",
        valid_from="17.08.2026", valid_to="22.08.2026",
        source_text="PDF Seite 1: Teilresultat", source_url="https://example.test/prospect",
        local_store_offer=True, confidence=.99,
    )

    class NoopArtifacts:
        def archive_before_import(self, db, store, result):
            return None

        def finalize_after_import(self, db, store, result, summary):
            return None

    result, summary, run = service.collect_structured_for_store(
        db,
        store.name,
        collector_fn=lambda source: {
            "offers": [row],
            "fetch_mode": "partial-test",
            "final_url": source.url,
            "technical_warning": "error_type=timeout phase=ocr_fallback",
        },
        artifact_handler=NoopArtifacts(),
    )

    assert summary.imported == 1
    assert run.status == "warning"
    assert "error_type=timeout phase=ocr_fallback" in run.message
    snapshot = db.query(CollectionQualitySnapshot).one()
    assert snapshot.run_status == "warning"
