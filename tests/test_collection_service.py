from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
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
