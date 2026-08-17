from app.admin_learning import apply_product_correction, resolve_product_alias
from app.admin_quality import build_quality_report
from app.admin_seed import seed_admin_catalog
from app.db import Base, SessionLocal, engine
from app.models import AdminAuditLog, MasterProduct, ProductAdminData, ProductAlias, ProductCategory


def test_admin_categories_seed_once():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_admin_catalog(db)
    first = db.query(ProductCategory).count()
    seed_admin_catalog(db)
    second = db.query(ProductCategory).count()
    assert first >= 10
    assert second == first
    db.close()


def test_product_correction_creates_learning_alias_and_locked_metadata():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_admin_catalog(db)
    key = "admin-learning-wrong-product|500g"
    product = db.query(MasterProduct).filter(MasterProduct.normalized_key == key).first()
    if not product:
        product = MasterProduct(name="Falsch gelesener Artikel", brand=None, package_size="500 g", normalized_key=key)
        db.add(product)
        db.commit()
        db.refresh(product)

    category = db.query(ProductCategory).filter(ProductCategory.slug == "molkerei-kuehlung").first()
    apply_product_correction(
        db,
        product,
        name="Korrekt gelesener Artikel",
        brand="Testmarke",
        package_size="500 g",
        category_id=category.id,
        notes="manuell geprüft",
    )
    db.commit()

    db.expire_all()
    corrected = db.get(MasterProduct, product.id)
    meta = db.query(ProductAdminData).filter_by(master_product_id=product.id).one()
    alias = db.query(ProductAlias).filter_by(alias_key=key).one()
    assert corrected.name == "Korrekt gelesener Artikel"
    assert corrected.brand == "Testmarke"
    assert meta.name_locked is True
    assert meta.category_locked is True
    assert meta.category_id == category.id
    assert alias.master_product_id == product.id
    assert resolve_product_alias(db, key).id == product.id
    assert db.query(AdminAuditLog).filter(AdminAuditLog.entity_id == str(product.id)).count() >= 1
    db.close()


def test_quality_report_flags_suspicious_missing_category_and_duplicates():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    rows = [
        ("2 Kassenbon hochladen und QR-Code scannen", "quality-bad-a"),
        ("Test Qualitätsprodukt", "quality-dup-a"),
        ("Test Qualitätsprodukt", "quality-dup-b"),
    ]
    for name, key in rows:
        if not db.query(MasterProduct).filter_by(normalized_key=key).first():
            db.add(MasterProduct(name=name, normalized_key=key))
    db.commit()

    report = build_quality_report(db)
    assert report["counts"]["suspicious"] >= 1
    assert report["counts"]["missing_category"] >= 1
    assert report["counts"]["duplicates"] >= 1
    assert any("Kassenbon" in product.name for product, _ in report["suspicious"])
    db.close()
