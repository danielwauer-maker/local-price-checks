from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_product_media_routes import _media_review_counts, _media_review_queue, _safe_return_to
from app.db import Base
from app.models import MasterProduct, MediaAsset
from app.product_media_library import ProductMediaLibraryMetadata


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_review_queue_treats_legacy_media_without_library_metadata_as_unreviewed():
    db = _db()
    product = MasterProduct(name="BR1E Milch", normalized_key="br1e-milch")
    db.add(product)
    db.flush()
    legacy = MediaAsset(kind="product", master_product_id=product.id, source_url="https://img.example/legacy.jpg", active=True)
    verified = MediaAsset(kind="product", master_product_id=product.id, source_url="https://img.example/verified.jpg", active=True)
    db.add_all([legacy, verified])
    db.flush()
    db.add(ProductMediaLibraryMetadata(media_asset_id=verified.id, verification_status="verified", quality_score=80))
    db.commit()

    rows = _media_review_queue(db, review_status="unreviewed")
    assert [row["asset"].id for row in rows] == [legacy.id]
    assert _media_review_counts(db) == {"total": 2, "unreviewed": 1, "verified": 1, "rejected": 0, "flagged": 0}


def test_review_queue_filters_flagged_and_low_quality_media():
    db = _db()
    product = MasterProduct(name="BR1E Joghurt", normalized_key="br1e-joghurt")
    db.add(product)
    db.flush()
    flagged = MediaAsset(kind="product", master_product_id=product.id, source_url="https://img.example/placeholder.jpg", active=False)
    low = MediaAsset(kind="product", master_product_id=product.id, source_url="https://img.example/low.jpg", active=True)
    good = MediaAsset(kind="product", master_product_id=product.id, source_url="https://img.example/good.jpg", active=True)
    db.add_all([flagged, low, good])
    db.flush()
    db.add_all([
        ProductMediaLibraryMetadata(media_asset_id=flagged.id, verification_status="rejected", quality_score=0, is_placeholder=True),
        ProductMediaLibraryMetadata(media_asset_id=low.id, verification_status="unreviewed", quality_score=40),
        ProductMediaLibraryMetadata(media_asset_id=good.id, verification_status="verified", quality_score=90),
    ])
    db.commit()

    flagged_rows = _media_review_queue(db, review_status="all", issue="flagged")
    low_rows = _media_review_queue(db, review_status="all", issue="low_quality")
    assert [row["asset"].id for row in flagged_rows] == [flagged.id]
    assert {row["asset"].id for row in low_rows} == {flagged.id, low.id}
    assert _media_review_counts(db)["flagged"] == 1


def test_review_queue_search_and_return_target_are_safe():
    db = _db()
    milk = MasterProduct(name="Frische Vollmilch", normalized_key="br1e-vollmilch")
    bread = MasterProduct(name="Roggenbrot", normalized_key="br1e-brot")
    db.add_all([milk, bread])
    db.flush()
    db.add_all([
        MediaAsset(kind="product", master_product_id=milk.id, source_url="https://img.example/milk.jpg", active=True),
        MediaAsset(kind="product", master_product_id=bread.id, source_url="https://img.example/bread.jpg", active=True),
    ])
    db.commit()

    rows = _media_review_queue(db, q="vollmilch", review_status="all")
    assert [row["product"].id for row in rows] == [milk.id]
    assert _safe_return_to("/admin/product-media-review?status=unreviewed") == "/admin/product-media-review?status=unreviewed"
    assert _safe_return_to("https://evil.example/") == "/admin/product-media-review"
    assert _safe_return_to("/admin/product-media-review\nLocation:https://evil.example") == "/admin/product-media-review"
