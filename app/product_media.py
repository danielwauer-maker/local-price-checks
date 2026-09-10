from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import MasterProduct, MediaAsset, MediaAssetMetadata
from .product_media_quality import library_metadata_map, public_media_usable, upsert_library_metadata

_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}
MEDIA_SOURCE_PRIORITY = {
    "prospect_crop": 100,
    "pdf_embedded": 150,
    "retailer_cdn": 250,
    "official_retailer": 300,
    "official_product": 350,
    "manufacturer_official": 400,
    "admin_curated": 450,
}


def media_source_for_asset(db: Session, asset: MediaAsset) -> str:
    metadata = db.query(MediaAssetMetadata).filter(
        MediaAssetMetadata.media_asset_id == asset.id
    ).first()
    if metadata:
        return metadata.media_source
    if (asset.source_url or "").startswith("prospect-crop:"):
        return "prospect_crop"
    if (asset.source_url or "").startswith(("http://", "https://")):
        return "retailer_cdn"
    return "admin_curated"


def _inferred_media_source(asset: MediaAsset) -> str:
    if (asset.source_url or "").startswith("prospect-crop:"):
        return "prospect_crop"
    if (asset.source_url or "").startswith(("http://", "https://")):
        return "retailer_cdn"
    return "admin_curated"


def _set_media_metadata(
    db: Session,
    asset: MediaAsset,
    *,
    media_source: str,
    external_product_id: str | None = None,
    canonical_url: str | None = None,
    audit_relevant: bool = False,
) -> MediaAssetMetadata:
    source = media_source if media_source in MEDIA_SOURCE_PRIORITY else "retailer_cdn"
    row = db.query(MediaAssetMetadata).filter(
        MediaAssetMetadata.media_asset_id == asset.id
    ).first()
    if row is None:
        row = MediaAssetMetadata(media_asset_id=asset.id, media_source=source)
        db.add(row)
    row.media_source = source
    row.priority = MEDIA_SOURCE_PRIORITY[source]
    row.audit_relevant = audit_relevant
    if external_product_id:
        row.external_product_id = external_product_id[:160]
    if canonical_url:
        row.canonical_url = canonical_url
    db.flush()
    return row


def preferred_product_media(db: Session, product_id: int, *, purpose: str = "public") -> MediaAsset | None:
    return preferred_product_media_map(db, [product_id], purpose=purpose).get(product_id)


def preferred_product_media_map(
    db: Session,
    product_ids: list[int],
    *,
    purpose: str = "public",
) -> dict[int, MediaAsset]:
    """Resolve preferred media with review-aware, non-degrading ranking."""
    if not product_ids:
        return {}
    assets = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.kind == "product",
            MediaAsset.master_product_id.in_(product_ids),
            MediaAsset.active.is_(True),
        )
        .all()
    )
    ids = [asset.id for asset in assets]
    metadata = {
        row.media_asset_id: row
        for row in db.query(MediaAssetMetadata)
        .filter(MediaAssetMetadata.media_asset_id.in_(ids)).all()
    } if ids else {}
    library = library_metadata_map(db, ids)

    def rank(asset: MediaAsset):
        meta = metadata.get(asset.id)
        lib = library.get(asset.id)
        source = meta.media_source if meta else _inferred_media_source(asset)
        priority = meta.priority if meta else MEDIA_SOURCE_PRIORITY.get(source, 0)
        audit = bool(meta.audit_relevant) if meta else source == "prospect_crop"
        if purpose == "audit":
            return (
                int(audit),
                int(source == "prospect_crop"),
                int(lib is None or lib.verification_status != "rejected"),
                priority,
                int(asset.is_primary),
                asset.id,
            )
        return (
            int(bool(lib.manual_preferred)) if lib else 0,
            int(lib.verification_status == "verified") if lib else 0,
            priority,
            int(asset.is_primary),
            int(lib.quality_score or 0) if lib else 0,
            int(not audit),
            asset.id,
        )

    grouped: dict[int, list[MediaAsset]] = {}
    for asset in assets:
        if asset.master_product_id is None:
            continue
        if purpose != "audit" and not public_media_usable(library.get(asset.id)):
            continue
        grouped.setdefault(asset.master_product_id, []).append(asset)
    return {product_id: max(rows, key=rank) for product_id, rows in grouped.items() if rows}


def _refresh_product_primary(db: Session, product_id: int) -> None:
    preferred = preferred_product_media(db, product_id, purpose="public")
    for asset in db.query(MediaAsset).filter(
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product_id,
        MediaAsset.active.is_(True),
    ):
        asset.is_primary = preferred is not None and asset.id == preferred.id


def _retire_rejected_prospect_crop(db: Session, product_id: int, source_url: str | None) -> int:
    """Deactivate only the exact crop that failed identity validation."""
    if not source_url or not source_url.startswith("prospect-crop:"):
        return 0
    assets = db.query(MediaAsset).filter(
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product_id,
        MediaAsset.source_url == source_url,
        MediaAsset.active.is_(True),
    ).all()
    retired = 0
    for asset in assets:
        if media_source_for_asset(db, asset) != "prospect_crop":
            continue
        asset.active = False
        asset.is_primary = False
        lib = library_metadata_map(db, [asset.id]).get(asset.id)
        if lib:
            lib.verification_status = "rejected"
            lib.manual_preferred = False
            lib.review_reason = lib.review_reason or "collector_crop_identity_rejected"
            lib.reviewed_at = datetime.utcnow()
        retired += 1
    if retired:
        _refresh_product_primary(db, product_id)
    return retired


def _image_extension(content_type: str, url: str) -> str | None:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in _CONTENT_EXTENSIONS:
        return _CONTENT_EXTENSIONS[mime]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return None


def _existing_payload(asset: MediaAsset, media_dir: Path | None = None) -> bytes | None:
    if not asset.file_path:
        return None
    path = (media_dir or (settings.data_dir / "admin_media")) / Path(asset.file_path).name
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return payload if 0 < len(payload) <= _MAX_IMAGE_BYTES else None


def persist_product_image(
    db: Session,
    product: MasterProduct,
    image_url: str | None,
    *,
    alt_text: str | None = None,
    media_dir: Path | None = None,
    media_source: str = "retailer_cdn",
    external_product_id: str | None = None,
    canonical_url: str | None = None,
    retailer: str | None = None,
    source_name: str | None = None,
    license_note: str | None = None,
    confidence: float | None = None,
) -> MediaAsset | None:
    """Persist product media while preserving explicit review/preference state."""
    url = (image_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None

    existing = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.kind == "product",
            MediaAsset.master_product_id == product.id,
            MediaAsset.source_url == url,
        )
        .order_by(MediaAsset.created_at.desc())
        .first()
    )
    if existing:
        if alt_text and not existing.alt_text:
            existing.alt_text = alt_text[:240]
        if retailer and not existing.retailer:
            existing.retailer = retailer[:80]
        existing.active = True
        _set_media_metadata(
            db, existing, media_source=media_source,
            external_product_id=external_product_id, canonical_url=canonical_url,
        )
        upsert_library_metadata(
            db, existing, media_source=media_source,
            payload=_existing_payload(existing, media_dir), source_name=source_name,
            retailer=retailer, license_note=license_note, confidence=confidence,
        )
        _refresh_product_primary(db, product.id)
        return existing

    try:
        with httpx.stream(
            "GET", url, timeout=20.0, follow_redirects=True,
            headers={"User-Agent": "LocalPriceChecks/1.0 product-media"},
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            extension = _image_extension(content_type, str(response.url))
            if not content_type.lower().startswith("image/") or not extension:
                return None
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > _MAX_IMAGE_BYTES:
                return None
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > _MAX_IMAGE_BYTES:
                    return None
                chunks.append(chunk)
            payload = b"".join(chunks)
    except (httpx.HTTPError, OSError, ValueError):
        return None

    if not payload:
        return None
    target_dir = media_dir or (settings.data_dir / "admin_media")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:24]
        filename = f"product-{product.id}-{digest}{extension}"
        target = target_dir / filename
        if not target.exists():
            target.write_bytes(payload)
    except OSError:
        return None

    has_primary = db.query(MediaAsset).filter(
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product.id,
        MediaAsset.active.is_(True),
        MediaAsset.is_primary.is_(True),
    ).first() is not None
    asset = MediaAsset(
        kind="product", master_product_id=product.id,
        retailer=(retailer or "")[:80] or None,
        file_path=filename, source_url=url,
        alt_text=(alt_text or product.name)[:240],
        mime_type=(content_type or "").split(";", 1)[0].strip().lower() or None,
        is_primary=not has_primary, active=True,
    )
    db.add(asset)
    db.flush()
    _set_media_metadata(
        db, asset, media_source=media_source,
        external_product_id=external_product_id, canonical_url=canonical_url,
    )
    upsert_library_metadata(
        db, asset, media_source=media_source, payload=payload,
        source_name=source_name, retailer=retailer,
        license_note=license_note, confidence=confidence,
    )
    _refresh_product_primary(db, product.id)
    return asset


def persist_product_image_file(
    db: Session,
    product: MasterProduct,
    image_path: str | Path | None,
    *,
    alt_text: str | None = None,
    media_dir: Path | None = None,
    media_source: str = "prospect_crop",
    retailer: str | None = None,
    source_name: str | None = None,
    license_note: str | None = None,
    confidence: float | None = None,
) -> MediaAsset | None:
    """Persist a collector crop without forcing it over a better primary image."""
    if not image_path:
        return None
    try:
        source = Path(image_path).resolve(strict=True)
        data_root = settings.data_dir.resolve(strict=False)
        if not source.is_file() or not source.is_relative_to(data_root):
            return None
        size = source.stat().st_size
        if size <= 0 or size > _MAX_IMAGE_BYTES:
            return None
        extension = source.suffix.lower()
        mime_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
        }.get(extension)
        if mime_type is None:
            return None
        payload = source.read_bytes()
    except (OSError, ValueError):
        return None

    content_digest = hashlib.sha256(payload).hexdigest()
    source_url = f"prospect-crop:{content_digest}"
    existing = db.query(MediaAsset).filter(
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product.id,
        MediaAsset.source_url == source_url,
    ).first()
    if existing:
        existing.active = True
        if retailer and not existing.retailer:
            existing.retailer = retailer[:80]
        _set_media_metadata(db, existing, media_source=media_source, audit_relevant=True)
        upsert_library_metadata(
            db, existing, media_source=media_source, payload=payload,
            source_name=source_name, retailer=retailer,
            license_note=license_note, confidence=confidence,
        )
        _refresh_product_primary(db, product.id)
        return existing

    target_dir = media_dir or (settings.data_dir / "admin_media")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"product-{product.id}-{content_digest[:24]}{'.jpg' if extension == '.jpeg' else extension}"
        target = target_dir / filename
        if not target.exists():
            target.write_bytes(payload)
    except OSError:
        return None

    has_primary = db.query(MediaAsset).filter(
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product.id,
        MediaAsset.active.is_(True),
        MediaAsset.is_primary.is_(True),
    ).first() is not None
    asset = MediaAsset(
        kind="product", master_product_id=product.id,
        retailer=(retailer or "")[:80] or None,
        file_path=filename, source_url=source_url,
        alt_text=(alt_text or product.name)[:240], mime_type=mime_type,
        is_primary=not has_primary, active=True,
    )
    db.add(asset)
    db.flush()
    _set_media_metadata(db, asset, media_source=media_source, audit_relevant=True)
    upsert_library_metadata(
        db, asset, media_source=media_source, payload=payload,
        source_name=source_name, retailer=retailer,
        license_note=license_note, confidence=confidence,
    )
    _refresh_product_primary(db, product.id)
    return asset


def persist_collected_product_images(db: Session, rows) -> int:
    """Attach collector media and preserve source/review provenance."""
    from .extractor_adapter import normalize_master_key

    saved = 0
    handled: set[tuple[int, str]] = set()
    for row in rows or []:
        image_url = (getattr(row, "image_url", None) or "").strip()
        image_path = (
            getattr(row, "audit_image_path", None)
            or getattr(row, "image_path", None)
            or ""
        ).strip()
        crop_rejected = bool(getattr(row, "crop_quality_rejected", False))
        rejected_crop_source_url = getattr(row, "rejected_crop_source_url", None)
        if not image_url and not image_path and not crop_rejected:
            continue
        try:
            key = normalize_master_key(
                getattr(row, "product_name", ""),
                getattr(row, "quantity", None),
                getattr(row, "unit", None),
            )
        except Exception:
            continue
        product = db.query(MasterProduct).filter(MasterProduct.normalized_key == key).first()
        if not product:
            continue

        if crop_rejected:
            _retire_rejected_prospect_crop(db, product.id, rejected_crop_source_url)

        retailer = getattr(row, "retailer", None)
        source_name = (
            getattr(row, "collector_source", None)
            or getattr(row, "source_key", None)
            or getattr(row, "source", None)
        )
        confidence = getattr(row, "image_confidence", None)
        if image_url:
            marker = (product.id, image_url)
            if marker not in handled:
                handled.add(marker)
                asset = persist_product_image(
                    db, product, image_url,
                    alt_text=getattr(row, "image_alt", None) or getattr(row, "product_name", None),
                    media_source=getattr(row, "image_media_source", None) or "retailer_cdn",
                    external_product_id=(
                        getattr(row, "retailer_product_id", None)
                        or getattr(row, "lidl_product_id", None)
                    ),
                    canonical_url=getattr(row, "canonical_url", None),
                    retailer=retailer, source_name=source_name, confidence=confidence,
                )
                if asset:
                    saved += 1
        if image_path:
            marker = (product.id, image_path)
            if marker in handled:
                continue
            handled.add(marker)
            asset = persist_product_image_file(
                db, product, image_path,
                alt_text=getattr(row, "image_alt", None) or getattr(row, "product_name", None),
                media_source="prospect_crop", retailer=retailer,
                source_name=source_name, confidence=confidence,
            )
            if asset:
                saved += 1
    db.commit()
    return saved
