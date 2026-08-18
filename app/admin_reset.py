from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .config import settings
from .models import (
    CollectionRun,
    FavoriteProduct,
    MasterProduct,
    MediaAsset,
    Offer,
    ProductAdminData,
    ProductAlias,
    ProductBarcode,
    ShoppingItem,
    Store,
)
from .prospect_models import (
    OfferProvenance,
    Prospect,
    ProspectArchive,
    ProspectMissingItem,
    ProspectOfferReview,
)


def _safe_unlink(path_value: str | None) -> None:
    if not path_value:
        return
    try:
        path = Path(path_value).resolve()
        data_root = settings.data_dir.resolve()
        if data_root == path or data_root in path.parents:
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _remove_product_media_file(row: MediaAsset) -> None:
    if not row.file_path:
        return
    try:
        path = (settings.data_dir / "admin_media" / Path(row.file_path).name).resolve()
        media_root = (settings.data_dir / "admin_media").resolve()
        if media_root in path.parents:
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _delete_offer_graph(db: Session, offer_ids: list[int]) -> dict[str, int]:
    if not offer_ids:
        return {"offers": 0, "provenance": 0, "reviews": 0}

    provenance_ids = [
        row[0]
        for row in db.query(OfferProvenance.id)
        .filter(OfferProvenance.offer_id.in_(offer_ids))
        .all()
    ]
    reviews = 0
    provenance = 0
    if provenance_ids:
        reviews = (
            db.query(ProspectOfferReview)
            .filter(ProspectOfferReview.offer_provenance_id.in_(provenance_ids))
            .delete(synchronize_session=False)
        )
        provenance = (
            db.query(OfferProvenance)
            .filter(OfferProvenance.id.in_(provenance_ids))
            .delete(synchronize_session=False)
        )
    offers = db.query(Offer).filter(Offer.id.in_(offer_ids)).delete(synchronize_session=False)
    return {"offers": offers, "provenance": provenance, "reviews": reviews}


def _prune_orphan_products(db: Session, candidate_ids: set[int]) -> int:
    """Remove products no longer used anywhere, while preserving user lists."""
    removed = 0
    for product_id in candidate_ids:
        if db.query(Offer.id).filter(Offer.master_product_id == product_id).first():
            continue
        if db.query(FavoriteProduct.id).filter(FavoriteProduct.master_product_id == product_id).first():
            continue
        if db.query(ShoppingItem.id).filter(ShoppingItem.master_product_id == product_id).first():
            continue

        media_rows = db.query(MediaAsset).filter(MediaAsset.master_product_id == product_id).all()
        for row in media_rows:
            _remove_product_media_file(row)
            db.delete(row)
        db.query(ProductBarcode).filter(ProductBarcode.master_product_id == product_id).delete(synchronize_session=False)
        db.query(ProductAlias).filter(ProductAlias.master_product_id == product_id).delete(synchronize_session=False)
        db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product_id).delete(synchronize_session=False)
        product = db.get(MasterProduct, product_id)
        if product:
            db.delete(product)
            removed += 1
    return removed


def reset_store_offers(db: Session, store: Store) -> dict[str, int]:
    """Delete collected offer data for one market, but keep prospect archives and release state."""
    rows = db.query(Offer.id, Offer.master_product_id).filter(Offer.store_id == store.id).all()
    offer_ids = [row[0] for row in rows]
    product_ids = {row[1] for row in rows}
    result = _delete_offer_graph(db, offer_ids)
    result["runs"] = db.query(CollectionRun).filter(CollectionRun.store_id == store.id).delete(synchronize_session=False)
    db.flush()
    result["orphan_products"] = _prune_orphan_products(db, product_ids)
    db.commit()
    return result


def reset_store_qa(db: Session, store: Store) -> dict[str, int]:
    """Return one market to a never-scraped QA state while preserving its master data/source."""
    rows = db.query(Offer.id, Offer.master_product_id).filter(Offer.store_id == store.id).all()
    offer_ids = [row[0] for row in rows]
    product_ids = {row[1] for row in rows}

    result = _delete_offer_graph(db, offer_ids)
    result["runs"] = db.query(CollectionRun).filter(CollectionRun.store_id == store.id).delete(synchronize_session=False)

    archives = db.query(ProspectArchive).filter(ProspectArchive.store_id == store.id).all()
    archive_ids = [row.id for row in archives]
    result["missing_items"] = 0
    if archive_ids:
        result["missing_items"] = (
            db.query(ProspectMissingItem)
            .filter(ProspectMissingItem.prospect_archive_id.in_(archive_ids))
            .delete(synchronize_session=False)
        )
        # Defensive cleanup for provenance not tied to currently existing offers.
        remaining_provenance_ids = [
            row[0]
            for row in db.query(OfferProvenance.id)
            .filter(OfferProvenance.prospect_archive_id.in_(archive_ids))
            .all()
        ]
        if remaining_provenance_ids:
            db.query(ProspectOfferReview).filter(
                ProspectOfferReview.offer_provenance_id.in_(remaining_provenance_ids)
            ).delete(synchronize_session=False)
            db.query(OfferProvenance).filter(
                OfferProvenance.id.in_(remaining_provenance_ids)
            ).delete(synchronize_session=False)

    for row in db.query(Prospect).filter(Prospect.store_id == store.id).all():
        _safe_unlink(row.local_path)
        db.delete(row)
    for row in archives:
        _safe_unlink(row.local_path)
        db.delete(row)

    store.benchmark_verified = False
    db.flush()
    result["orphan_products"] = _prune_orphan_products(db, product_ids)
    result["prospects"] = len(archives)
    db.commit()
    return result


def reset_all_test_data(db: Session) -> dict[str, int]:
    """Clear all collected/catalog QA data while preserving stores, regions and configuration."""
    counts = {
        "offers": db.query(Offer).count(),
        "products": db.query(MasterProduct).count(),
        "runs": db.query(CollectionRun).count(),
        "archives": db.query(ProspectArchive).count(),
    }

    db.query(ProspectOfferReview).delete(synchronize_session=False)
    db.query(OfferProvenance).delete(synchronize_session=False)
    db.query(ProspectMissingItem).delete(synchronize_session=False)
    db.query(Offer).delete(synchronize_session=False)
    db.query(CollectionRun).delete(synchronize_session=False)
    db.query(Prospect).delete(synchronize_session=False)
    db.query(ProspectArchive).delete(synchronize_session=False)

    # User product state must be cleared before deleting the product catalog.
    db.query(FavoriteProduct).delete(synchronize_session=False)
    db.query(ShoppingItem).delete(synchronize_session=False)

    product_media = db.query(MediaAsset).filter(MediaAsset.master_product_id.is_not(None)).all()
    for row in product_media:
        _remove_product_media_file(row)
        db.delete(row)
    db.query(ProductBarcode).delete(synchronize_session=False)
    db.query(ProductAlias).delete(synchronize_session=False)
    db.query(ProductAdminData).delete(synchronize_session=False)
    db.query(MasterProduct).delete(synchronize_session=False)

    # A clean controlled QA restart: no market may refill itself via the verified scheduler.
    for store in db.query(Store).all():
        store.benchmark_verified = False

    db.commit()

    prospect_root = settings.data_dir / "prospects"
    try:
        if prospect_root.exists():
            shutil.rmtree(prospect_root)
        prospect_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    return counts
