from datetime import date

from app.db import Base, SessionLocal, engine
from app.models import MasterProduct, Offer, Store
from app.prospect_models import (
    OfferProvenance,
    ProspectArchive,
    ProspectMissingItem,
    ProspectOfferReview,
)


def _fixture_rows(db):
    store = db.query(Store).filter_by(name="Audit Test Store").first()
    if not store:
        store = Store(
            retailer="Audit",
            name="Audit Test Store",
            postal_code="57614",
            city="Steimel",
            address="Test 1",
            active=True,
            benchmark_verified=False,
        )
        db.add(store)
        db.flush()

    product = db.query(MasterProduct).filter_by(normalized_key="audit-test-product").first()
    if not product:
        product = MasterProduct(name="Audit Test Product", normalized_key="audit-test-product")
        db.add(product)
        db.flush()

    archive = db.query(ProspectArchive).filter_by(store_id=store.id, pdf_sha256="a" * 64).first()
    if not archive:
        archive = ProspectArchive(
            store_id=store.id,
            retailer=store.retailer,
            period_key="current",
            valid_from=date(2026, 8, 17),
            valid_to=date(2026, 8, 22),
            source_url="https://example.invalid/prospect",
            pdf_url="https://example.invalid/prospect.pdf",
            original_filename="audit.pdf",
            page_count=4,
            pdf_sha256="a" * 64,
            pdf_bytes=b"%PDF-1.4 audit",
        )
        db.add(archive)
        db.flush()

    offer = db.query(Offer).filter_by(store_id=store.id, master_product_id=product.id, valid_from=date(2026, 8, 17), price=1.99).first()
    if not offer:
        offer = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=1.99,
            valid_from=date(2026, 8, 17),
            valid_to=date(2026, 8, 22),
            local_store_offer=True,
        )
        db.add(offer)
        db.flush()

    provenance = db.query(OfferProvenance).filter_by(offer_id=offer.id, prospect_archive_id=archive.id, prospect_page=2).first()
    if not provenance:
        provenance = OfferProvenance(
            offer_id=offer.id,
            prospect_archive_id=archive.id,
            prospect_page=2,
            source_text="PDF Seite 2: Audit Test Product 1,99",
        )
        db.add(provenance)
        db.flush()
    return store, product, archive, offer, provenance


def test_prospect_offer_review_persists_structured_learning_signal():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    _, _, _, _, provenance = _fixture_rows(db)
    db.query(ProspectOfferReview).filter_by(offer_provenance_id=provenance.id).delete()
    db.add(
        ProspectOfferReview(
            offer_provenance_id=provenance.id,
            status="incorrect",
            issue_type="wrong_price",
            expected_price=1.49,
            notes="Preis im PDF manuell geprüft",
        )
    )
    db.commit()
    row = db.query(ProspectOfferReview).filter_by(offer_provenance_id=provenance.id).one()
    assert row.status == "incorrect"
    assert row.issue_type == "wrong_price"
    assert row.expected_price == 1.49
    assert row.provenance.prospect_page == 2
    assert "PDF Seite 2" in row.provenance.source_text
    db.close()


def test_missing_pdf_item_can_be_recorded_per_page():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    _, _, archive, _, _ = _fixture_rows(db)
    db.query(ProspectMissingItem).filter_by(prospect_archive_id=archive.id, expected_name="Nicht erkannter Artikel").delete()
    db.add(
        ProspectMissingItem(
            prospect_archive_id=archive.id,
            prospect_page=3,
            expected_name="Nicht erkannter Artikel",
            expected_brand="Testmarke",
            expected_package_size="500 g",
            expected_price=2.49,
        )
    )
    db.commit()
    row = db.query(ProspectMissingItem).filter_by(prospect_archive_id=archive.id, expected_name="Nicht erkannter Artikel").one()
    assert row.prospect_page == 3
    assert row.expected_price == 2.49
    assert row.resolved is False
    db.close()
