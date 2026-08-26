from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from .config import settings
from .collection_quality import CollectionQualitySnapshot
from .models import (
    CollectionRun,
    CollectionRunProgress,
    FavoriteProduct,
    MasterProduct,
    MediaAsset,
    MediaAssetMetadata,
    Offer,
    ProductAdminData,
    ProductAlias,
    ProductBarcode,
    ShoppingItem,
    Store,
)
from .offer_cleanup import delete_offer_graph
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
            db.query(MediaAssetMetadata).filter(
                MediaAssetMetadata.media_asset_id == row.id
            ).delete(synchronize_session=False)
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
    result = delete_offer_graph(db, offer_ids)
    from .market_activation import StoreActivationState, StoreQualityAssessment
    state = db.query(StoreActivationState).filter_by(store_id=store.id).first()
    if state:
        state.last_test_run_id = None
        db.flush()
    result["activation_assessments"] = db.query(StoreQualityAssessment).filter_by(
        store_id=store.id
    ).delete(synchronize_session=False)
    result["quality_snapshots"] = (
        db.query(CollectionQualitySnapshot)
        .filter(CollectionQualitySnapshot.store_id == store.id)
        .delete(synchronize_session=False)
    )
    run_ids = [row[0] for row in db.query(CollectionRun.id).filter(CollectionRun.store_id == store.id).all()]
    result["run_progress"] = (
        db.query(CollectionRunProgress)
        .filter(CollectionRunProgress.run_id.in_(run_ids))
        .delete(synchronize_session=False)
        if run_ids else 0
    )
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

    from .market_activation import StoreActivationState, StoreQualityAssessment
    result = delete_offer_graph(db, offer_ids)
    state = db.query(StoreActivationState).filter_by(store_id=store.id).first()
    if state:
        state.last_test_run_id = None
        state.lifecycle_status = "promoted"
        state.manually_suspended = False
        state.suspension_reason = None
        state.last_error = None
        db.flush()
    result["activation_assessments"] = db.query(StoreQualityAssessment).filter_by(
        store_id=store.id
    ).delete(synchronize_session=False)
    result["quality_snapshots"] = (
        db.query(CollectionQualitySnapshot)
        .filter(CollectionQualitySnapshot.store_id == store.id)
        .delete(synchronize_session=False)
    )
    run_ids = [row[0] for row in db.query(CollectionRun.id).filter(CollectionRun.store_id == store.id).all()]
    result["run_progress"] = (
        db.query(CollectionRunProgress)
        .filter(CollectionRunProgress.run_id.in_(run_ids))
        .delete(synchronize_session=False)
        if run_ids else 0
    )
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
    from .market_activation import StoreActivationState, StoreQualityAssessment
    counts = {
        "offers": db.query(Offer).count(),
        "products": db.query(MasterProduct).count(),
        "runs": db.query(CollectionRun).count(),
        "quality_snapshots": db.query(CollectionQualitySnapshot).count(),
        "run_progress": db.query(CollectionRunProgress).count(),
        "archives": db.query(ProspectArchive).count(),
    }

    delete_offer_graph(db, [row[0] for row in db.query(Offer.id).all()])
    db.query(ProspectMissingItem).delete(synchronize_session=False)
    for state in db.query(StoreActivationState).all():
        state.last_test_run_id = None
        state.lifecycle_status = "promoted"
        state.manually_suspended = False
        state.suspension_reason = None
        state.last_error = None
    db.flush()
    db.query(StoreQualityAssessment).delete(synchronize_session=False)
    db.query(CollectionQualitySnapshot).delete(synchronize_session=False)
    db.query(CollectionRunProgress).delete(synchronize_session=False)
    db.query(CollectionRun).delete(synchronize_session=False)
    db.query(Prospect).delete(synchronize_session=False)
    db.query(ProspectArchive).delete(synchronize_session=False)

    # User product state must be cleared before deleting the product catalog.
    db.query(FavoriteProduct).delete(synchronize_session=False)
    db.query(ShoppingItem).delete(synchronize_session=False)

    product_media = db.query(MediaAsset).filter(MediaAsset.master_product_id.is_not(None)).all()
    for row in product_media:
        _remove_product_media_file(row)
        db.query(MediaAssetMetadata).filter(
            MediaAssetMetadata.media_asset_id == row.id
        ).delete(synchronize_session=False)
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
