from __future__ import annotations

import hashlib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from .models import MediaAsset
from .product_media_library import ProductMediaLibraryMetadata

SOURCE_QUALITY_BASE = {
    "prospect_crop": 30,
    "pdf_embedded": 35,
    "retailer_cdn": 50,
    "official_retailer": 65,
    "official_product": 70,
    "manufacturer_official": 75,
    "admin_curated": 70,
}
_PLACEHOLDER_TOKENS = (
    "placeholder", "no-image", "no_image", "noimage",
    "image-not-found", "missing-image", "dummy-image",
)


def inspect_image(payload: bytes, source_hint: str | None, media_source: str) -> dict[str, object]:
    result: dict[str, object] = {
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "width": None, "height": None, "image_format": None,
        "aspect_ratio": None, "perceptual_hash": None,
    }
    path = "" if not source_hint or source_hint.startswith("prospect-crop:") else urlparse(source_hint).path.lower()
    filename = Path(path).stem
    placeholder = any(token in path for token in _PLACEHOLDER_TOKENS)
    logo = filename == "logo" or filename.startswith("logo-") or filename.endswith("-logo")
    result["is_placeholder"] = placeholder
    result["is_logo"] = logo
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
            result.update(
                width=int(width), height=int(height),
                image_format=(image.format or "").lower() or None,
                aspect_ratio=round(width / height, 4) if height else None,
            )
            gray = image.convert("L").resize((9, 8))
            pixels = list(gray.getdata())
            value = 0
            for row in range(8):
                offset = row * 9
                for col in range(8):
                    value = (value << 1) | int(pixels[offset + col] > pixels[offset + col + 1])
            result["perceptual_hash"] = f"{value:016x}"
    except (UnidentifiedImageError, OSError, ValueError):
        # Legacy fixtures can carry image MIME with minimal payloads. Review,
        # not a decoder failure alone, owns the durable broken-image decision.
        pass

    score = SOURCE_QUALITY_BASE.get(media_source, 40)
    width, height = result["width"], result["height"]
    if isinstance(width, int) and isinstance(height, int):
        shortest = min(width, height)
        score += 20 if shortest >= 800 else 15 if shortest >= 400 else 8 if shortest >= 200 else -15 if shortest < 100 else 0
        ratio = width / height if height else 0
        if ratio < 0.35 or ratio > 3.0:
            score -= 10
    if placeholder or logo:
        score = 0
    result["quality_score"] = max(0, min(100, int(score)))
    return result


def upsert_library_metadata(
    db: Session,
    asset: MediaAsset,
    *,
    media_source: str,
    payload: bytes | None = None,
    source_name: str | None = None,
    retailer: str | None = None,
    license_note: str | None = None,
    confidence: float | None = None,
) -> ProductMediaLibraryMetadata:
    now = datetime.utcnow()
    row = db.query(ProductMediaLibraryMetadata).filter(
        ProductMediaLibraryMetadata.media_asset_id == asset.id
    ).first()
    if row is None:
        row = ProductMediaLibraryMetadata(
            media_asset_id=asset.id,
            first_observed_at=now,
            last_observed_at=now,
            verification_status="unreviewed",
            is_broken=False,
            is_placeholder=False,
            is_logo=False,
            manual_preferred=False,
        )
        db.add(row)
    row.last_observed_at = now
    if source_name:
        row.source_name = source_name[:120]
    if retailer:
        row.retailer = retailer[:80]
    if license_note:
        row.license_note = license_note
    if confidence is not None:
        row.confidence = max(0.0, min(1.0, float(confidence)))
    if payload:
        quality = inspect_image(payload, asset.source_url, media_source)
        row.width = quality["width"]
        row.height = quality["height"]
        row.image_format = quality["image_format"]
        row.aspect_ratio = quality["aspect_ratio"]
        row.content_sha256 = quality["content_sha256"]
        row.perceptual_hash = quality["perceptual_hash"]
        row.quality_score = quality["quality_score"]
        if row.verification_status != "verified":
            row.is_placeholder = bool(quality["is_placeholder"])
            row.is_logo = bool(quality["is_logo"])
    db.flush()
    return row


def library_metadata_map(db: Session, media_ids: list[int]) -> dict[int, ProductMediaLibraryMetadata]:
    if not media_ids:
        return {}
    return {
        row.media_asset_id: row
        for row in db.query(ProductMediaLibraryMetadata)
        .filter(ProductMediaLibraryMetadata.media_asset_id.in_(media_ids)).all()
    }


def public_media_usable(row: ProductMediaLibraryMetadata | None) -> bool:
    return row is None or not (
        row.verification_status == "rejected"
        or bool(row.is_broken) or bool(row.is_placeholder) or bool(row.is_logo)
    )


def review_library_metadata(
    db: Session,
    asset: MediaAsset,
    *,
    media_source: str,
    status: str,
    actor: str | None,
    reason: str | None = None,
    is_broken: bool | None = None,
    is_placeholder: bool | None = None,
    is_logo: bool | None = None,
) -> ProductMediaLibraryMetadata:
    normalized = status.strip().lower()
    if normalized not in {"unreviewed", "verified", "rejected"}:
        raise ValueError("invalid verification status")
    row = upsert_library_metadata(db, asset, media_source=media_source, retailer=asset.retailer)
    row.verification_status = normalized
    if is_broken is not None:
        row.is_broken = is_broken
    if is_placeholder is not None:
        row.is_placeholder = is_placeholder
    if is_logo is not None:
        row.is_logo = is_logo
    row.review_reason = reason or None
    row.reviewed_by = (actor or "")[:120] or None
    row.reviewed_at = datetime.utcnow()
    if normalized == "rejected" or row.is_broken or row.is_placeholder or row.is_logo:
        row.manual_preferred = False
    db.flush()
    return row
