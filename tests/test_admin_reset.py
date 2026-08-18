from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_reset import reset_all_test_data, reset_store_offers, reset_store_qa
from app.coverage_models import CoverageRegion
from app.db import Base
from app.models import (
    CollectionRun,
    FavoriteProduct,
    MasterProduct,
    Offer,
    ShoppingItem,
    Store,
    UserProfile,
)
from app.prospect_models import (
    OfferProvenance,
    Prospect,
    ProspectArchive,
    ProspectMissingItem,
    ProspectOfferReview,
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def _store(name: str, verified: bool = True) -> Store:
    return Store(
        retailer="REWE",
        name=name,
        postal_code="56589",
        city="Teststadt",
        address="Testweg 1",
        active=True,
        benchmark_verified=verified,
    )


def test_offer_reset_preserves_prospect_release_and_other_store_products():
    db = _db()
    a = _store("Markt A")
    b = _store("Markt B")
    shared = MasterProduct(name="Gemeinsam", normalized_key="gemeinsam")
    only_a = MasterProduct(name="Nur A", normalized_key="nur-a")
    db.add_all([a, b, shared, only_a])
    db.flush()
    offer_a_shared = Offer(store_id=a.id, master_product_id=shared.id, price=1.0, valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 23))
    offer_a_only = Offer(store_id=a.id, master_product_id=only_a.id, price=2.0, valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 23))
    offer_b_shared = Offer(store_id=b.id, master_product_id=shared.id, price=1.0, valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 23))
    db.add_all([offer_a_shared, offer_a_only, offer_b_shared])
    db.flush()
    archive = ProspectArchive(
        store_id=a.id, retailer=a.retailer, period_key="current",
        source_url="https://example.test", pdf_url="https://example.test/a.pdf",
        page_count=1, pdf_sha256="a" * 64, pdf_bytes=b"%PDF-test",
    )
    db.add(archive)
    db.flush()
    db.add(Prospect(
        store_id=a.id, period_key="current", source_url="https://example.test",
        pdf_url="https://example.test/a.pdf", local_path="/tmp/not-used.pdf", page_count=1,
    ))
    db.add(OfferProvenance(offer_id=offer_a_shared.id, prospect_archive_id=archive.id, prospect_page=1))
    db.add(CollectionRun(store_id=a.id, source_key="test", status="success", offers_received=2, offers_imported=2))
    db.commit()

    result = reset_store_offers(db, a)

    assert result["offers"] == 2
    assert db.query(Offer).filter(Offer.store_id == a.id).count() == 0
    assert db.query(Offer).filter(Offer.store_id == b.id).count() == 1
    assert db.get(MasterProduct, shared.id) is not None
    assert db.query(MasterProduct).filter(MasterProduct.normalized_key == "nur-a").count() == 0
    assert db.query(ProspectArchive).filter(ProspectArchive.store_id == a.id).count() == 1
    assert db.query(Prospect).filter(Prospect.store_id == a.id).count() == 1
    assert db.get(Store, a.id).benchmark_verified is True
    db.close()


def test_qa_reset_removes_prospect_audit_and_returns_store_to_qa():
    db = _db()
    store = _store("QA Markt", verified=True)
    product = MasterProduct(name="Artikel", normalized_key="artikel")
    db.add_all([store, product])
    db.flush()
    offer = Offer(store_id=store.id, master_product_id=product.id, price=1.5, valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 23))
    db.add(offer)
    db.flush()
    archive = ProspectArchive(
        store_id=store.id, retailer=store.retailer, period_key="current",
        source_url="https://example.test", pdf_url="web-snapshot://https://example.test",
        page_count=2, pdf_sha256="b" * 64, pdf_bytes=b"%PDF-test",
    )
    db.add(archive)
    db.flush()
    provenance = OfferProvenance(offer_id=offer.id, prospect_archive_id=archive.id, prospect_page=1)
    db.add(provenance)
    db.flush()
    db.add(ProspectOfferReview(offer_provenance_id=provenance.id, status="correct"))
    db.add(ProspectMissingItem(prospect_archive_id=archive.id, prospect_page=2, expected_name="Fehlt"))
    db.add(Prospect(store_id=store.id, period_key="current", source_url="https://example.test", pdf_url="web-snapshot://https://example.test", local_path="/tmp/not-used.pdf", page_count=2))
    db.commit()

    reset_store_qa(db, store)

    assert db.query(Offer).filter(Offer.store_id == store.id).count() == 0
    assert db.query(ProspectArchive).filter(ProspectArchive.store_id == store.id).count() == 0
    assert db.query(Prospect).filter(Prospect.store_id == store.id).count() == 0
    assert db.query(ProspectOfferReview).count() == 0
    assert db.query(ProspectMissingItem).count() == 0
    assert db.get(Store, store.id).benchmark_verified is False
    db.close()


def test_global_reset_keeps_store_region_and_configuration_shape_but_clears_catalog():
    db = _db()
    store = _store("Bleibt", verified=True)
    user = UserProfile(display_name="Test")
    product = MasterProduct(name="Weg", normalized_key="weg")
    region = CoverageRegion(name="Testregion", center_lat=50.0, center_lng=7.0, radius_km=15, status="live", active=True)
    db.add_all([store, user, product, region])
    db.flush()
    db.add(Offer(store_id=store.id, master_product_id=product.id, price=3.0, valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 23)))
    db.add(FavoriteProduct(user_id=user.id, master_product_id=product.id))
    db.add(ShoppingItem(user_id=user.id, master_product_id=product.id, quantity=1))
    db.add(CollectionRun(store_id=store.id, source_key="test", status="success", offers_received=1, offers_imported=1))
    db.commit()

    result = reset_all_test_data(db)

    assert result["products"] == 1
    assert db.query(MasterProduct).count() == 0
    assert db.query(Offer).count() == 0
    assert db.query(FavoriteProduct).count() == 0
    assert db.query(ShoppingItem).count() == 0
    assert db.query(CollectionRun).count() == 0
    assert db.query(Store).count() == 1
    assert db.query(CoverageRegion).count() == 1
    assert db.get(Store, store.id).benchmark_verified is False
    db.close()
