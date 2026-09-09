from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import MasterProduct
from app.product_catalog import (
    backfill_master_product_profiles,
    canonical_family_key,
    ensure_master_product_profile,
    parse_package_size,
    profile_snapshot,
)
from app.product_catalog_models import MasterProductProfile


def _isolated_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    MasterProduct.__table__.create(bind=engine)
    MasterProductProfile.__table__.create(bind=engine)
    return sessionmaker(bind=engine, future=True)()


def test_parse_simple_package_size_conservatively():
    facts = parse_package_size("500 g")
    assert facts.value == 500.0
    assert facts.unit == "g"
    assert facts.count is None
    assert facts.total_quantity == 500.0
    assert facts.comparison_unit == "kg"


def test_parse_multipack_without_guessing_promotional_text():
    facts = parse_package_size("6 x 0,33 l")
    assert facts.value == 0.33
    assert facts.unit == "l"
    assert facts.count == 6
    assert round(facts.total_quantity or 0.0, 2) == 1.98
    assert facts.comparison_unit == "l"

    unknown = parse_package_size("verschiedene Sorten, Vorteilspack")
    assert unknown.value is None
    assert unknown.unit is None
    assert unknown.total_quantity is None


def test_profile_creation_is_idempotent_and_package_independent_family_key():
    db = _isolated_session()
    try:
        product = MasterProduct(
            brand="Example",
            name="Haferdrink Natur",
            package_size="1 l",
            normalized_key="example haferdrink natur|1l",
        )
        db.add(product)
        db.flush()

        first = ensure_master_product_profile(db, product, data_source="collector", confidence=0.91)
        second = ensure_master_product_profile(db, product, data_source="collector", confidence=0.95)
        db.commit()

        assert first.id == second.id
        assert db.query(MasterProductProfile).count() == 1
        assert first.family_key == canonical_family_key(product)
        assert "|1l" not in (first.family_key or "")
        assert first.package_value == 1.0
        assert first.package_unit == "l"
        assert first.comparison_unit == "l"
        assert first.confidence == 0.95
        assert first.data_source == "collector"
    finally:
        db.close()


def test_verified_profile_is_not_overwritten_by_recurring_collection():
    db = _isolated_session()
    try:
        product = MasterProduct(
            brand="Example",
            name="Joghurt Natur",
            package_size="500 g",
            normalized_key="example joghurt natur|500g",
        )
        db.add(product)
        db.flush()
        profile = ensure_master_product_profile(db, product, data_source="admin", confidence=1.0)
        profile.canonical_name = "Kuratierter Joghurt Natur"
        profile.product_family = "Naturjoghurt"
        profile.verification_status = "verified"
        profile.package_value = 450.0
        profile.package_unit = "g"
        db.commit()

        product.name = "Collector Name Changed"
        product.package_size = "600 g"
        ensure_master_product_profile(db, product, data_source="collector", confidence=0.2)
        db.commit()
        db.refresh(profile)

        assert profile.canonical_name == "Kuratierter Joghurt Natur"
        assert profile.product_family == "Naturjoghurt"
        assert profile.package_value == 450.0
        assert profile.package_unit == "g"
        assert profile.verification_status == "verified"
        assert profile.confidence == 1.0
        assert profile.data_source == "admin"
    finally:
        db.close()


def test_backfill_creates_only_missing_profiles_and_snapshot_is_stable():
    db = _isolated_session()
    try:
        products = [
            MasterProduct(name="Milch 1,5%", package_size="1 l", normalized_key="milch 1 5|1l"),
            MasterProduct(name="Butter", package_size="250 g", normalized_key="butter|250g"),
        ]
        db.add_all(products)
        db.flush()
        ensure_master_product_profile(db, products[0], data_source="collector", confidence=0.8)
        db.commit()

        assert backfill_master_product_profiles(db, batch_size=1) == 1
        db.commit()
        assert backfill_master_product_profiles(db, batch_size=1) == 0
        assert db.query(MasterProductProfile).count() == 2

        profile = db.query(MasterProductProfile).filter_by(master_product_id=products[1].id).one()
        snapshot = profile_snapshot(profile)
        assert snapshot["canonicalName"] == "Butter"
        assert snapshot["package"]["value"] == 250.0
        assert snapshot["package"]["unit"] == "g"
        assert snapshot["verificationStatus"] == "unverified"
        assert 0.0 <= snapshot["completeness"] <= 1.0
    finally:
        db.close()
