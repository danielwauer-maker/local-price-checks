from app.admin_learning import infer_learned_brand
from app.db import SessionLocal
from app.models import MasterProduct, ProductAdminData


def test_admin_corrected_brand_is_a_high_confidence_prefix_signal():
    db = SessionLocal()
    product = MasterProduct(
        name="Milka Referenzprodukt",
        brand="Milka",
        normalized_key="brand-learning-milka-reference",
    )
    try:
        db.add(product)
        db.flush()
        db.add(ProductAdminData(master_product_id=product.id, name_locked=True))
        db.commit()
        assert infer_learned_brand(db, "Milka Schokolade Alpenmilch") == "Milka"
        assert infer_learned_brand(db, "Schokolade Milka Alpenmilch") is None
    finally:
        if product.id:
            meta = db.query(ProductAdminData).filter_by(master_product_id=product.id).first()
            if meta:
                db.delete(meta)
            stored = db.get(MasterProduct, product.id)
            if stored:
                db.delete(stored)
            db.commit()
        db.close()


def test_generic_first_words_are_never_inferred_without_brand_evidence():
    db = SessionLocal()
    try:
        assert infer_learned_brand(db, "Frische Feigen") is None
        assert infer_learned_brand(db, "Bio Mini Möhren") is None
        assert infer_learned_brand(db, "Deutsche Rote Zwiebeln") is None
        assert infer_learned_brand(db, "Helle kernlose Trauben") is None
    finally:
        db.close()
