from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_quality import build_prospect_provenance_report
from app.db import Base
from app.models import MasterProduct, Offer, Store
from app.prospect_models import OfferProvenance, ProspectArchive


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def _setup(db):
    store = Store(retailer="REWE", name="REWE QA Test", postal_code="12345", city="Test", address="Test 1", benchmark_verified=True)
    product_a = MasterProduct(name="Produkt A", normalized_key="qa-product-a")
    product_b = MasterProduct(name="Produkt B", normalized_key="qa-product-b")
    db.add_all([store, product_a, product_b])
    db.flush()
    archive = ProspectArchive(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        valid_from=date(2026, 8, 17),
        valid_to=date(2026, 8, 23),
        source_url="https://example.test/rewe",
        pdf_url="https://example.test/rewe.pdf",
        original_filename="rewe.pdf",
        page_count=26,
        pdf_sha256="b" * 64,
        pdf_bytes=b"%PDF-qa",
    )
    offer_a = Offer(store_id=store.id, master_product_id=product_a.id, price=1.99, valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 23), source_url=archive.source_url)
    offer_b = Offer(store_id=store.id, master_product_id=product_b.id, price=2.99, valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 23), source_url=archive.source_url)
    db.add_all([archive, offer_a, offer_b])
    db.flush()
    return archive, offer_a, offer_b


def test_provenance_report_reaches_100_percent_when_every_offer_has_valid_page():
    db = _db()
    archive, offer_a, offer_b = _setup(db)
    db.add_all([
        OfferProvenance(offer_id=offer_a.id, prospect_archive_id=archive.id, prospect_page=4),
        OfferProvenance(offer_id=offer_b.id, prospect_archive_id=archive.id, prospect_page=17),
    ])
    db.commit()

    report = build_prospect_provenance_report(db)
    row = report["rows"][0]
    assert row["offers_total"] == 2
    assert row["offers_with_pdf"] == 2
    assert row["offers_with_page"] == 2
    assert row["page_coverage_pct"] == 100.0
    assert row["status"] == "released"
    assert report["counts"]["offers_without_page"] == 0
    db.close()


def test_provenance_report_blocks_when_offer_has_no_page_reference():
    db = _db()
    archive, offer_a, _offer_b = _setup(db)
    db.add(OfferProvenance(offer_id=offer_a.id, prospect_archive_id=archive.id, prospect_page=4))
    db.commit()

    report = build_prospect_provenance_report(db)
    row = report["rows"][0]
    assert row["offers_total"] == 2
    assert row["offers_with_page"] == 1
    assert row["offers_without_page"] == 1
    assert row["page_coverage_pct"] == 50.0
    assert row["status"] == "blocked"
    db.close()


def test_provenance_report_flags_page_outside_pdf_range():
    db = _db()
    archive, offer_a, _offer_b = _setup(db)
    db.add(OfferProvenance(offer_id=offer_a.id, prospect_archive_id=archive.id, prospect_page=99))
    db.commit()

    report = build_prospect_provenance_report(db)
    row = report["rows"][0]
    assert row["invalid_page_links"] == 1
    assert row["offers_with_page"] == 0
    assert row["status"] == "blocked"
    db.close()
