from pathlib import Path

from pypdf import PdfWriter

from app.db import Base, SessionLocal, engine
from app.models import Store
from app.prospect_models import Prospect
from app.prospects import save_prospect


def test_save_prospect_persists_local_pdf_and_page_count(tmp_path: Path):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter(Store.name == "Prospect Test Store").first()
    if not store:
        store = Store(retailer="TEST", name="Prospect Test Store", postal_code="00000", city="Test", address="Test 1", active=True, benchmark_verified=True)
        db.add(store)
        db.commit()
        db.refresh(store)

    pdf = tmp_path / "prospect.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with pdf.open("wb") as handle:
        writer.write(handle)

    row = save_prospect(db, store, period_key="current", source_url="https://example.test/prospect", pdf_url="https://example.test/prospect.pdf", pdf_path=pdf)
    assert row.page_count == 2
    assert row.period_key == "current"
    assert Path(row.local_path) == pdf
    assert db.query(Prospect).filter_by(store_id=store.id, period_key="current").count() == 1
    db.close()
