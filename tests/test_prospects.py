from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfWriter

from app.clock import app_today
from app.db import Base, SessionLocal, engine
from app.models import Store
from app.prospect_models import Prospect
from app.prospects import current_prospect, save_manual_prospect, save_prospect


def _blank_pdf(path: Path, pages: int = 2) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)
    return path.read_bytes()


def test_save_prospect_persists_local_pdf_and_page_count(tmp_path: Path):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter(Store.name == "Prospect Test Store").first()
    if not store:
        store = Store(retailer="TEST", name="Prospect Test Store", postal_code="00000", city="Test", address="Test 1", active=True, benchmark_verified=True)
        db.add(store); db.commit(); db.refresh(store)
    pdf = tmp_path / "prospect.pdf"
    _blank_pdf(pdf, 2)
    row = save_prospect(db, store, period_key="current", source_url="https://example.test/prospect", pdf_url="https://example.test/prospect.pdf", pdf_path=pdf)
    assert row.page_count == 2
    assert row.period_key == "current"
    assert Path(row.local_path) == pdf
    assert db.query(Prospect).filter_by(store_id=store.id, period_key="current").count() == 1
    db.close()


def test_synthetic_rewe_catalog_is_not_exposed_as_real_prospect(tmp_path: Path):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter(Store.name == "REWE Prospect Test").first()
    if not store:
        store = Store(retailer="REWE", name="REWE Prospect Test", postal_code="00000", city="Test", address="Test 2", active=True, benchmark_verified=True, external_id="321019")
        db.add(store); db.commit(); db.refresh(store)
    pdf = tmp_path / "rewe-angebotskatalog.pdf"
    _blank_pdf(pdf, 12)
    today = app_today()
    row = save_prospect(db, store, period_key="current", source_url="https://rewe.example/market", pdf_url="https://rewe.example/market", pdf_path=pdf, valid_from=today, valid_to=today + timedelta(days=6))
    assert current_prospect(db, store, "current") is None
    db.refresh(row)
    assert row.active is False
    db.close()


def test_manual_rewe_original_pdf_is_saved_and_kept(tmp_path: Path, monkeypatch):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter(Store.name == "REWE Manual Prospect Test").first()
    if not store:
        store = Store(retailer="REWE", name="REWE Manual Prospect Test", postal_code="00000", city="Test", address="Test 3", active=True, benchmark_verified=True, external_id="321019")
        db.add(store); db.commit(); db.refresh(store)
    source = tmp_path / "rewe_2026_wk34_321019.pdf"
    payload = _blank_pdf(source, 26)
    monkeypatch.setattr("app.prospects.settings", SimpleNamespace(data_dir=tmp_path))
    row = save_manual_prospect(db, store, period_key="current", filename=source.name, payload=payload)
    assert row.page_count == 26
    assert row.source_url == f"admin-upload://{source.name}"
    assert current_prospect(db, store, "current").id == row.id
    db.close()


def test_manual_rewe_pdf_rejects_other_market_id(tmp_path: Path, monkeypatch):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter(Store.name == "REWE Wrong Market Test").first()
    if not store:
        store = Store(retailer="REWE", name="REWE Wrong Market Test", postal_code="00000", city="Test", address="Test 4", active=True, benchmark_verified=True, external_id="321019")
        db.add(store); db.commit(); db.refresh(store)
    source = tmp_path / "rewe_2026_wk34_999999.pdf"
    payload = _blank_pdf(source, 2)
    monkeypatch.setattr("app.prospects.settings", SimpleNamespace(data_dir=tmp_path))
    try:
        save_manual_prospect(db, store, period_key="current", filename=source.name, payload=payload)
        assert False, "wrong market PDF should have been rejected"
    except ValueError as exc:
        assert "anderen REWE-Markt" in str(exc)
    db.close()
