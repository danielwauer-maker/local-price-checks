from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Store
import app.prospects as prospects


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def test_rewe_uses_automatic_official_web_snapshot_when_no_pdf(monkeypatch, tmp_path):
    db = _db()
    store = Store(
        retailer="REWE",
        name="REWE Dennis Weirich",
        postal_code="56587",
        city="Straßenhaus",
        address="Kirschbüchel 2",
        external_id="1940425",
        source_url="https://www.rewe.de/angebote/strassenhaus/1940425/rewe-markt-kirschbuechel-2/",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    monkeypatch.setattr(prospects, "discover_official_pdf", lambda _url: (_ for _ in ()).throw(RuntimeError("no pdf")))

    def fake_snapshot(_store, _url, target_dir: Path):
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "official-web-test.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with target.open("wb") as handle:
            writer.write(handle)
        return target

    monkeypatch.setattr(prospects, "_render_official_web_snapshot", fake_snapshot)
    monkeypatch.setattr(prospects, "_link_web_snapshot_provenance", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(prospects.settings, "data_dir", tmp_path)

    row = prospects.discover_and_store_prospect(db, store, "current")
    assert row is not None
    assert row.pdf_url.startswith("web-snapshot://")
    assert row.source_url == store.source_url
    assert row.page_count == 1
    archive = db.query(prospects.ProspectArchive).filter_by(store_id=store.id).one()
    assert archive.pdf_url.startswith("web-snapshot://")
    assert archive.pdf_bytes.startswith(b"%PDF")
    db.close()
