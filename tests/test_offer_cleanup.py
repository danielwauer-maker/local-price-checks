from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Base, create_database_engine
from app.models import MasterProduct, Offer, OfferOccurrence, OfferPriceReference, Store
from app.offer_cleanup import delete_offer_graph
from app.prospect_models import OfferProvenance, ProspectArchive, ProspectOfferReview


def _session():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _offer_graph(db):
    store = Store(
        retailer="REWE",
        name="FK-Testmarkt",
        postal_code="56589",
        city="Teststadt",
        address="Testweg 1",
    )
    product = MasterProduct(name="Testprodukt", normalized_key="testprodukt")
    db.add_all([store, product])
    db.flush()
    offer = Offer(
        store_id=store.id,
        master_product_id=product.id,
        price=1.0,
        valid_from=date(2026, 8, 17),
        valid_to=date(2026, 8, 23),
    )
    archive = ProspectArchive(
        store_id=store.id,
        retailer=store.retailer,
        period_key="current",
        source_url="https://example.test",
        pdf_url="https://example.test/prospect.pdf",
        page_count=1,
        pdf_sha256="f" * 64,
        pdf_bytes=b"%PDF-test",
    )
    db.add_all([offer, archive])
    db.flush()
    provenance = OfferProvenance(offer_id=offer.id, prospect_archive_id=archive.id, prospect_page=1)
    db.add(provenance)
    db.flush()
    db.add_all(
        [
            OfferOccurrence(offer_id=offer.id, occurrence_fingerprint="fk-cleanup"),
            OfferPriceReference(offer_id=offer.id, reference_price=1.5),
            ProspectOfferReview(offer_provenance_id=provenance.id, status="correct"),
        ]
    )
    db.commit()
    return offer.id


def test_sqlite_connections_enable_foreign_keys_and_reject_invalid_children():
    db = _session()
    assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    db.add(OfferOccurrence(offer_id=999_999, occurrence_fingerprint="invalid-parent"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_delete_offer_graph_removes_every_child_without_foreign_key_violations():
    db = _session()
    offer_id = _offer_graph(db)

    result = delete_offer_graph(db, [offer_id])
    db.commit()

    assert result == {
        "offers": 1,
        "occurrences": 1,
        "price_references": 1,
        "provenance": 1,
        "reviews": 1,
    }
    assert db.query(Offer).count() == 0
    assert db.query(OfferOccurrence).count() == 0
    assert db.query(OfferPriceReference).count() == 0
    assert db.query(OfferProvenance).count() == 0
    assert db.query(ProspectOfferReview).count() == 0
    assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    db.close()
