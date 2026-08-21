from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.admin_routes import _admin
from app.api_main import app
from app.clock import app_today
from app.db import Base, SessionLocal, engine
from app.models import MasterProduct, Offer, Store
from app.prospect_models import OfferProvenance, ProspectArchive, ProspectOfferReview


@pytest.fixture
def admin_client():
    app.dependency_overrides[_admin] = lambda: "test-admin"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(_admin, None)


def _setup_review_offer():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter_by(name="QA Review Testmarkt").first()
    if not store:
        store = Store(
            retailer="EDEKA",
            name="QA Review Testmarkt",
            postal_code="00000",
            city="Test",
            address="Test 1",
            active=True,
            benchmark_verified=False,
            latitude=50.0,
            longitude=7.0,
        )
        db.add(store)
        db.flush()

    product = db.query(MasterProduct).filter_by(normalized_key="qa-review-test-product").first()
    if not product:
        product = MasterProduct(
            name="QA Review Test Produkt",
            normalized_key="qa-review-test-product",
            brand="Testmarke",
            package_size="500 g",
        )
        db.add(product)
        db.flush()

    today = app_today()
    offer = (
        db.query(Offer)
        .filter_by(store_id=store.id, master_product_id=product.id, valid_from=today, price=1.99)
        .first()
    )
    if not offer:
        offer = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=1.99,
            valid_from=today,
            valid_to=today + timedelta(days=6),
            local_store_offer=True,
        )
        db.add(offer)
        db.flush()

    archive = db.query(ProspectArchive).filter_by(store_id=store.id, pdf_sha256="a" * 64).first()
    if not archive:
        archive = ProspectArchive(
            store_id=store.id,
            retailer="EDEKA",
            period_key="current",
            valid_from=today,
            valid_to=today + timedelta(days=6),
            source_url="https://example.test/market",
            pdf_url="https://example.test/flyer.pdf",
            original_filename="test.pdf",
            local_path=None,
            page_count=4,
            pdf_sha256="a" * 64,
            pdf_bytes=b"%PDF-test",
        )
        db.add(archive)
        db.flush()

    provenance = (
        db.query(OfferProvenance)
        .filter_by(offer_id=offer.id, prospect_archive_id=archive.id, prospect_page=3)
        .first()
    )
    if not provenance:
        provenance = OfferProvenance(
            offer_id=offer.id,
            prospect_archive_id=archive.id,
            prospect_page=3,
            source_text="Testmarke QA Review Test Produkt 500 g 1,99 €",
            source_url=archive.pdf_url,
        )
        db.add(provenance)
        db.flush()

    db.query(ProspectOfferReview).filter_by(offer_provenance_id=provenance.id).delete()
    db.commit()
    ids = store.id, product.id, provenance.id
    db.close()
    return ids


def test_review_metadata_requires_admin_auth():
    store_id, _, _ = _setup_review_offer()
    client = TestClient(app)

    response = client.get(f"/api/offer-reviews?market_ids={store_id}")

    assert response.status_code in {401, 503}


def test_review_metadata_includes_unreleased_market_offer_and_provenance(admin_client):
    store_id, product_id, provenance_id = _setup_review_offer()

    response = admin_client.get(f"/api/offer-reviews?market_ids={store_id}")

    assert response.status_code == 200
    rows = response.json()
    row = next(item for item in rows if item["productId"] == str(product_id))
    assert row["provenanceId"] == provenance_id
    assert row["prospectPage"] == 3
    assert row["prospectPages"] == [3]
    assert row["product"]["name"] == "QA Review Test Produkt"
    assert row["market"]["id"] == str(store_id)
    assert row["price"]["offer"]["price"] == 1.99
    assert row["reviewStatus"] is None


def test_quick_error_review_is_persisted_for_prospect_audit(admin_client):
    _, _, provenance_id = _setup_review_offer()

    response = admin_client.put(f"/api/offer-reviews/{provenance_id}", json={"status": "incorrect"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["reviewStatus"] == "incorrect"
    assert payload["reviewIssueType"] == "webapp_flagged"
    assert "prospect-audit" in payload["auditUrl"]

    db = SessionLocal()
    review = db.query(ProspectOfferReview).filter_by(offer_provenance_id=provenance_id).one()
    assert review.status == "incorrect"
    assert review.issue_type == "webapp_flagged"
    assert review.reviewed_by == "test-admin"
    db.close()


def test_quick_correct_can_clear_only_transient_webapp_error_marker(admin_client):
    _, _, provenance_id = _setup_review_offer()
    admin_client.put(f"/api/offer-reviews/{provenance_id}", json={"status": "incorrect"})

    response = admin_client.put(f"/api/offer-reviews/{provenance_id}", json={"status": "correct"})

    assert response.status_code == 200
    assert response.json()["reviewStatus"] == "correct"
    assert response.json()["reviewIssueType"] is None
