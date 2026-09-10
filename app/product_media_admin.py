from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import MediaAsset, MediaAssetMetadata
from .product_media_library import ProductMediaLibraryMetadata
from .product_media_quality import library_metadata_map, review_library_metadata, upsert_library_metadata


def _source_for_asset(db: Session, asset: MediaAsset) -> str:
    meta = db.query(MediaAssetMetadata).filter(MediaAssetMetadata.media_asset_id == asset.id).first()
    if meta:
        return meta.media_source
    if (asset.source_url or "").startswith("prospect-crop:"):
        return "prospect_crop"
    if (asset.source_url or "").startswith(("http://", "https://")):
        return "retailer_cdn"
    return "admin_curated"


def set_preferred_product_media(
    db: Session, product_id: int, media_id: int, *, actor: str | None = None
) -> MediaAsset:
    from .product_media import _refresh_product_primary

    asset = db.query(MediaAsset).filter(
        MediaAsset.id == media_id,
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product_id,
        MediaAsset.active.is_(True),
    ).first()
    if asset is None:
        raise ValueError("product media not found")

    assets = db.query(MediaAsset).filter(
        MediaAsset.kind == "product", MediaAsset.master_product_id == product_id
    ).all()
    lib_map = library_metadata_map(db, [row.id for row in assets])
    selected = lib_map.get(media_id)
    if selected is None:
        selected = upsert_library_metadata(db, asset, media_source=_source_for_asset(db, asset))
        lib_map[media_id] = selected
    if (
        selected.verification_status == "rejected"
        or selected.is_broken
        or selected.is_placeholder
        or selected.is_logo
    ):
        raise ValueError("unusable product media cannot be preferred")

    for row in lib_map.values():
        row.manual_preferred = row.media_asset_id == media_id
    selected.reviewed_by = (actor or "")[:120] or None
    selected.reviewed_at = datetime.utcnow()
    _refresh_product_primary(db, product_id)
    db.flush()
    return asset


def review_product_media(
    db: Session,
    product_id: int,
    media_id: int,
    *,
    verification_status: str,
    actor: str | None = None,
    reason: str | None = None,
    is_broken: bool | None = None,
    is_placeholder: bool | None = None,
    is_logo: bool | None = None,
) -> ProductMediaLibraryMetadata:
    from .product_media import _refresh_product_primary

    asset = db.query(MediaAsset).filter(
        MediaAsset.id == media_id,
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product_id,
    ).first()
    if asset is None:
        raise ValueError("product media not found")
    row = review_library_metadata(
        db,
        asset,
        media_source=_source_for_asset(db, asset),
        status=verification_status,
        actor=actor,
        reason=reason,
        is_broken=is_broken,
        is_placeholder=is_placeholder,
        is_logo=is_logo,
    )
    unusable = (
        row.verification_status == "rejected"
        or bool(row.is_broken)
        or bool(row.is_placeholder)
        or bool(row.is_logo)
    )
    # Keep the row/file for provenance but remove unusable media from public
    # coverage. A later explicit clean review can reactivate the same media ID.
    asset.active = not unusable
    if unusable:
        asset.is_primary = False
    _refresh_product_primary(db, product_id)
    return row


def product_media_library(db: Session, product_id: int) -> list[dict[str, object]]:
    assets = db.query(MediaAsset).filter(
        MediaAsset.kind == "product", MediaAsset.master_product_id == product_id
    ).order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc()).all()
    ids = [row.id for row in assets]
    source_map = {
        row.media_asset_id: row
        for row in db.query(MediaAssetMetadata)
        .filter(MediaAssetMetadata.media_asset_id.in_(ids)).all()
    } if ids else {}
    lib_map = library_metadata_map(db, ids)
    hashes: dict[str, int] = {}
    for row in lib_map.values():
        if row.content_sha256:
            hashes[row.content_sha256] = hashes.get(row.content_sha256, 0) + 1

    result: list[dict[str, object]] = []
    for asset in assets:
        meta = source_map.get(asset.id)
        lib = lib_map.get(asset.id)
        source = meta.media_source if meta else _source_for_asset(db, asset)
        result.append({
            "id": asset.id,
            "active": asset.active,
            "is_primary": asset.is_primary,
            "file_path": asset.file_path,
            "source_url": asset.source_url,
            "mime_type": asset.mime_type,
            "media_source": source,
            "source_priority": meta.priority if meta else None,
            "external_product_id": meta.external_product_id if meta else None,
            "canonical_url": meta.canonical_url if meta else None,
            "audit_relevant": meta.audit_relevant if meta else source == "prospect_crop",
            "source_name": lib.source_name if lib else None,
            "retailer": lib.retailer if lib else asset.retailer,
            "license_note": lib.license_note if lib else None,
            "confidence": lib.confidence if lib else None,
            "first_observed_at": lib.first_observed_at if lib else asset.created_at,
            "last_observed_at": lib.last_observed_at if lib else asset.created_at,
            "width": lib.width if lib else None,
            "height": lib.height if lib else None,
            "image_format": lib.image_format if lib else None,
            "aspect_ratio": lib.aspect_ratio if lib else None,
            "content_sha256": lib.content_sha256 if lib else None,
            "perceptual_hash": lib.perceptual_hash if lib else None,
            "duplicate_count": hashes.get(lib.content_sha256, 0) if lib and lib.content_sha256 else 0,
            "quality_score": lib.quality_score if lib else None,
            "is_placeholder": bool(lib.is_placeholder) if lib else False,
            "is_logo": bool(lib.is_logo) if lib else False,
            "verification_status": lib.verification_status if lib else "unreviewed",
            "is_broken": bool(lib.is_broken) if lib else False,
            "manual_preferred": bool(lib.manual_preferred) if lib else False,
            "review_reason": lib.review_reason if lib else None,
            "reviewed_by": lib.reviewed_by if lib else None,
            "reviewed_at": lib.reviewed_at if lib else None,
        })
    return result
