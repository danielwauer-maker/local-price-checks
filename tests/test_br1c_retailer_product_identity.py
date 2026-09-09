from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data_operations_models import RetailerProduct, SourceProduct
from app.db import Base
from app.models import MasterProduct, Store
from app.price_observations import ensure_source_product


def _row(**overrides):
    values = {
        "source_key": "fixture",
        "product_name": "Test Produkt",
        "confidence": 0.95,
        "external_product_id": None,
        "external_product_scope": None,
        "retailer_product_id": None,
        "ean": None,
        "gtin": None,
        "lidl_product_id": None,
        "product_id": None,
        "article_id": None,
        "sku": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(retailer: str, suffix: str) -> Store:
    return Store(
        retailer=retailer,
        name=f"{retailer} {suffix}",
        postal_code="56269",
        city="Teststadt",
        address=f"Testweg {suffix}",
    )


def test_same_valid_gtin_reuses_one_retailer_product_across_stores():
    db = _session()
    try:
        product = MasterProduct(name="Milch", normalized_key="milch-1l")
        first_store = _store("REWE", "1")
        second_store = _store("REWE", "2")
        db.add_all([product, first_store, second_store])
        db.flush()

        row = _row(ean="4006381333931")
        first = ensure_source_product(db, row=row, store=first_store, product=product, observed_at=datetime(2026, 9, 9, 8))
        second = ensure_source_product(db, row=row, store=second_store, product=product, observed_at=datetime(2026, 9, 9, 9))
        db.flush()

        assert first.id != second.id
        assert first.store_id != second.store_id
        assert first.retailer_product_id == second.retailer_product_id
        retailer_product = db.get(RetailerProduct, first.retailer_product_id)
        assert retailer_product is not None
        assert retailer_product.identity_type == "gtin"
        assert retailer_product.identity_value == "4006381333931"
        assert retailer_product.master_product_id == product.id
        assert db.query(RetailerProduct).count() == 1
        assert db.query(SourceProduct).count() == 2
    finally:
        db.close()


def test_same_gtin_is_kept_separate_between_retailers():
    db = _session()
    try:
        product = MasterProduct(name="Markenprodukt", normalized_key="markenprodukt")
        rewe = _store("REWE", "A")
        edeka = _store("EDEKA", "B")
        db.add_all([product, rewe, edeka])
        db.flush()
        row = _row(gtin="4006381333931")

        left = ensure_source_product(db, row=row, store=rewe, product=product, observed_at=datetime(2026, 9, 9, 8))
        right = ensure_source_product(db, row=row, store=edeka, product=product, observed_at=datetime(2026, 9, 9, 9))
        db.flush()

        assert left.retailer_product_id != right.retailer_product_id
        assert db.query(RetailerProduct).count() == 2
    finally:
        db.close()


def test_generic_external_id_does_not_create_retailer_identity_without_scope():
    db = _session()
    try:
        product = MasterProduct(name="Joghurt", normalized_key="joghurt")
        store = _store("REWE", "C")
        db.add_all([product, store])
        db.flush()

        source = ensure_source_product(
            db,
            row=_row(external_product_id="12345"),
            store=store,
            product=product,
            observed_at=datetime(2026, 9, 9, 8),
        )
        db.flush()

        assert source.retailer_product_id is None
        assert db.query(RetailerProduct).count() == 0
    finally:
        db.close()


def test_explicit_retailer_scoped_external_id_creates_identity():
    db = _session()
    try:
        product = MasterProduct(name="Butter", normalized_key="butter")
        store = _store("REWE", "D")
        db.add_all([product, store])
        db.flush()

        source = ensure_source_product(
            db,
            row=_row(external_product_id="R-7788", external_product_scope="retailer"),
            store=store,
            product=product,
            observed_at=datetime(2026, 9, 9, 8),
        )
        db.flush()

        retailer_product = db.get(RetailerProduct, source.retailer_product_id)
        assert retailer_product is not None
        assert retailer_product.identity_type == "retailer_product_id"
        assert retailer_product.identity_value == "R-7788"
    finally:
        db.close()


def test_invalid_gtin_does_not_become_strong_identity():
    db = _session()
    try:
        product = MasterProduct(name="Saft", normalized_key="saft")
        store = _store("EDEKA", "E")
        db.add_all([product, store])
        db.flush()

        source = ensure_source_product(
            db,
            row=_row(ean="4006381333932"),
            store=store,
            product=product,
            observed_at=datetime(2026, 9, 9, 8),
        )
        db.flush()

        assert source.retailer_product_id is None
        assert db.query(RetailerProduct).count() == 0
    finally:
        db.close()


def test_conflicting_strong_identity_never_remaps_master_product():
    db = _session()
    try:
        first_product = MasterProduct(name="Produkt A", normalized_key="product-a")
        second_product = MasterProduct(name="Produkt B", normalized_key="product-b")
        first_store = _store("REWE", "F")
        second_store = _store("REWE", "G")
        db.add_all([first_product, second_product, first_store, second_store])
        db.flush()
        row = _row(ean="4006381333931")

        first = ensure_source_product(db, row=row, store=first_store, product=first_product, observed_at=datetime(2026, 9, 9, 8))
        second = ensure_source_product(db, row=row, store=second_store, product=second_product, observed_at=datetime(2026, 9, 9, 9))
        db.flush()

        retailer_product = db.get(RetailerProduct, first.retailer_product_id)
        assert retailer_product is not None
        assert retailer_product.master_product_id == first_product.id
        assert second.retailer_product_id is None
        assert second.master_product_id == second_product.id
        assert db.query(RetailerProduct).count() == 1
    finally:
        db.close()
