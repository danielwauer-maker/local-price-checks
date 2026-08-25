from sqlalchemy.orm import sessionmaker

from app.admin_seed import seed_admin_catalog
from app.category_classifier import reclassify_products
from app.db import Base, create_database_engine
from app.models import MasterProduct, ProductAdminData, ProductCategory


def test_reclassification_is_dry_run_first_and_respects_admin_lock():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    seed_admin_catalog(db)
    cola = MasterProduct(name="Pepsi Max", normalized_key="backfill-pepsi")
    locked = MasterProduct(name="Junger Gouda", normalized_key="backfill-locked-gouda")
    unknown = MasterProduct(name="Mystery Artikel 123", normalized_key="backfill-unknown")
    db.add_all([cola, locked, unknown])
    db.flush()
    sonstiges = db.query(ProductCategory).filter_by(slug="sonstiges").one()
    db.add(ProductAdminData(master_product_id=locked.id, category_id=sonstiges.id, category_locked=True))
    db.commit()

    dry_run = reclassify_products(db)
    assert dry_run.inspected == 3
    assert dry_run.changed == 1
    assert dry_run.locked == 1
    assert dry_run.unknown == 1
    assert db.query(ProductAdminData).filter_by(master_product_id=cola.id).first() is None
    assert db.query(ProductAdminData).filter_by(master_product_id=locked.id).one().category_id == sonstiges.id

    applied = reclassify_products(db, apply=True)
    cola_category = (
        db.query(ProductCategory)
        .join(ProductAdminData, ProductAdminData.category_id == ProductCategory.id)
        .filter(ProductAdminData.master_product_id == cola.id)
        .one()
    )
    assert applied.changed == 1
    assert cola_category.slug == "cola"
    assert db.query(ProductAdminData).filter_by(master_product_id=locked.id).one().category_id == sonstiges.id
    assert db.query(ProductAdminData).filter_by(master_product_id=unknown.id).first() is None
    db.close()


def test_unknown_reclassification_preserves_existing_plausible_category():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    seed_admin_catalog(db)
    product = MasterProduct(name="Mystery Spezialität 123", normalized_key="preserve-category")
    db.add(product)
    db.flush()
    fish = db.query(ProductCategory).filter_by(slug="fisch-produkte").one()
    db.add(ProductAdminData(master_product_id=product.id, category_id=fish.id))
    db.commit()

    dry_run = reclassify_products(db)
    entry = dry_run.entries[0]
    assert dry_run.unknown == 1
    assert dry_run.changed == 0
    assert entry.status == "unknown"
    assert entry.old_category == fish.name
    assert entry.new_category == fish.name
    assert "bleibt erhalten" in entry.reason

    applied = reclassify_products(db, apply=True)
    assert applied.unknown == 1
    assert db.query(ProductAdminData).filter_by(master_product_id=product.id).one().category_id == fish.id
    db.close()


def test_reclassification_corrects_vegan_meat_terms_and_kefir_sahne():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    seed_admin_catalog(db)
    vegan = MasterProduct(name="Vegetarische Bratwurst", normalized_key="vegetarische-bratwurst")
    kefir = MasterProduct(name="MILRAM Kefir Drink", normalized_key="milram-kefir")
    db.add_all([vegan, kefir])
    db.flush()
    wurst = db.query(ProductCategory).filter_by(slug="wurst").one()
    sahne = db.query(ProductCategory).filter_by(slug="sahne").one()
    db.add_all(
        [
            ProductAdminData(master_product_id=vegan.id, category_id=wurst.id),
            ProductAdminData(master_product_id=kefir.id, category_id=sahne.id),
        ]
    )
    db.commit()

    dry_run = reclassify_products(db)
    proposed = {entry.product_name: entry.new_category for entry in dry_run.entries}
    assert dry_run.changed == 2
    assert proposed == {
        "Vegetarische Bratwurst": "Fleischersatz",
        "MILRAM Kefir Drink": "Milchprodukte",
    }

    applied = reclassify_products(db, apply=True)
    assigned = {
        product.name: category.slug
        for product, category in (
            db.query(MasterProduct, ProductCategory)
            .join(ProductAdminData, ProductAdminData.master_product_id == MasterProduct.id)
            .join(ProductCategory, ProductCategory.id == ProductAdminData.category_id)
            .all()
        )
    }
    assert applied.changed == 2
    assert assigned == {
        "Vegetarische Bratwurst": "fleischersatz",
        "MILRAM Kefir Drink": "molkerei",
    }
    db.close()
