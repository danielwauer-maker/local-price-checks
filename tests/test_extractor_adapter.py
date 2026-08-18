from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.extractor_adapter import import_collected_offers, normalize_master_key
from app.models import MasterProduct, Offer, Store
from app.prospect_models import OfferProvenance, ProspectArchive
from app.engine_v140.collectors import CollectedOffer


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def _row(**changes):
    data = dict(
        source_key="rewe_test",
        store_name="REWE Test",
        retailer="REWE",
        product_name="Dallmayr Prodomo",
        category="Kaffee",
        price=6.49,
        quantity=500.0,
        unit="g",
        unit_price=12.98,
        unit_price_unit="kg",
        valid_from="17.08.2026",
        valid_to="22.08.2026",
        source_text="Prospekt Produktkarte",
        source_url="https://www.rewe.de/angebote/test/",
        local_store_offer=True,
        confidence=.99,
    )
    data.update(changes)
    return CollectedOffer(**data)


def test_import_creates_master_product_and_offer():
    db = _db()
    db.add(Store(retailer="REWE", name="REWE Test", postal_code="12345", city="Test", address="Test 1", benchmark_verified=True))
    db.commit()

    summary = import_collected_offers(db, [_row()])
    assert summary.imported == 1
    assert summary.created_products == 1
    assert summary.created_offers == 1
    product = db.query(MasterProduct).one()
    offer = db.query(Offer).one()
    assert product.name == "Dallmayr Prodomo"
    assert product.package_size == "500 g"
    assert offer.price == 6.49
    assert offer.unit_price == 12.98


def test_duplicate_offer_is_updated_not_duplicated():
    db = _db()
    db.add(Store(retailer="REWE", name="REWE Test", postal_code="12345", city="Test", address="Test 1", benchmark_verified=True))
    db.commit()
    import_collected_offers(db, [_row()])
    summary = import_collected_offers(db, [_row(unit_price=12.97)])
    assert summary.updated_offers == 1
    assert db.query(Offer).count() == 1
    assert db.query(Offer).one().unit_price == 12.97


def test_pdf_offer_is_linked_to_archived_prospect_page():
    db = _db()
    store = Store(retailer="REWE", name="REWE Test", postal_code="12345", city="Test", address="Test 1", benchmark_verified=True)
    db.add(store)
    db.flush()
    archive = ProspectArchive(
        store_id=store.id,
        retailer="REWE",
        period_key="current",
        valid_from=date(2026, 8, 17),
        valid_to=date(2026, 8, 22),
        source_url="https://www.rewe.de/angebote/test/",
        pdf_url="https://cdn.example/rewe.pdf",
        original_filename="rewe.pdf",
        local_path="/tmp/rewe.pdf",
        page_count=26,
        pdf_sha256="a" * 64,
        pdf_bytes=b"%PDF-test",
    )
    db.add(archive)
    db.commit()

    summary = import_collected_offers(db, [_row(source_text="PDF Seite 7: Prospekt Produktkarte")])
    assert summary.imported == 1
    provenance = db.query(OfferProvenance).one()
    assert provenance.prospect_archive_id == archive.id
    assert provenance.prospect_page == 7
    assert provenance.offer_id == db.query(Offer).one().id


def test_online_only_offer_is_rejected():
    db = _db()
    db.add(Store(retailer="REWE", name="REWE Test", postal_code="12345", city="Test", address="Test 1", benchmark_verified=True))
    db.commit()
    summary = import_collected_offers(db, [_row(source_text="Nur online bestellbar")])
    assert summary.rejected_online == 1
    assert db.query(Offer).count() == 0


def test_invalid_or_wrong_store_is_not_silently_mapped():
    db = _db()
    db.add(Store(retailer="ALDI SÜD", name="REWE Test", postal_code="12345", city="Test", address="Test 1", benchmark_verified=True))
    db.commit()
    summary = import_collected_offers(db, [_row()])
    assert summary.rejected_store == 1
    assert db.query(Offer).count() == 0


def test_master_key_ignores_generic_sorten_and_origin_noise_but_keeps_pack():
    a = normalize_master_key("Deutschland - LEIBNIZ Butterkeks versch. Sorten", 200, "g")
    b = normalize_master_key("LEIBNIZ Butterkeks", 200, "g")
    c = normalize_master_key("LEIBNIZ Butterkeks", 150, "g")
    assert a == b
    assert a != c
