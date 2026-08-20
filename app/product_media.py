from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import MasterProduct, MediaAsset, MediaAssetMetadata

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
    "retailer_cdn": 200,
    "official_product": 300,
    "admin_curated": 400,
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
    row.external_product_id = (external_product_id or "")[:160] or None
    row.canonical_url = canonical_url or None
    db.flush()
    return row


def preferred_product_media(db: Session, product_id: int, *, purpose: str = "public") -> MediaAsset | None:
    assets = db.query(MediaAsset).filter(
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product_id,
        MediaAsset.active.is_(True),
    ).all()
    if not assets:
        return None
    metadata = {
        row.media_asset_id: row
        for row in db.query(MediaAssetMetadata).filter(
            MediaAssetMetadata.media_asset_id.in_([asset.id for asset in assets])
        )
    }

    def rank(asset: MediaAsset) -> tuple[int, int, int, int]:
        meta = metadata.get(asset.id)
        source = meta.media_source if meta else media_source_for_asset(db, asset)
        priority = meta.priority if meta else MEDIA_SOURCE_PRIORITY[source]
        audit = bool(meta.audit_relevant) if meta else source == "prospect_crop"
        if purpose == "audit":
            return (int(audit), int(source == "prospect_crop"), priority, asset.id)
        return (priority, int(asset.is_primary), int(not audit), asset.id)

    return max(assets, key=rank)


def _refresh_product_primary(db: Session, product_id: int) -> None:
    preferred = preferred_product_media(db, product_id, purpose="public")
    if preferred is None:
        return
    for asset in db.query(MediaAsset).filter(
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product_id,
        MediaAsset.active.is_(True),
    ):
        asset.is_primary = asset.id == preferred.id


def _image_extension(content_type: str, url: str) -> str | None:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in _CONTENT_EXTENSIONS:
        return _CONTENT_EXTENSIONS[mime]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return None


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
) -> MediaAsset | None:
    """Persist one retailer product image locally and attach it to a product.

    Failures are non-fatal: an unavailable retailer CDN must never make an
    otherwise valid offer import fail. Existing primary media is preserved.
    """
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
        existing.active = True
        _set_media_metadata(
            db,
            existing,
            media_source=media_source,
            external_product_id=external_product_id,
            canonical_url=canonical_url,
        )
        _refresh_product_primary(db, product.id)
        return existing

    try:
        with httpx.stream(
            "GET",
            url,
            timeout=20.0,
            follow_redirects=True,
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

    has_primary = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.kind == "product",
            MediaAsset.master_product_id == product.id,
            MediaAsset.active.is_(True),
            MediaAsset.is_primary.is_(True),
        )
        .first()
        is not None
    )
    asset = MediaAsset(
        kind="product",
        master_product_id=product.id,
        file_path=filename,
        source_url=url,
        alt_text=(alt_text or product.name)[:240],
        mime_type=(content_type or "").split(";", 1)[0].strip().lower() or None,
        is_primary=not has_primary,
        active=True,
    )
    db.add(asset)
    db.flush()
    _set_media_metadata(
        db,
        asset,
        media_source=media_source,
        external_product_id=external_product_id,
        canonical_url=canonical_url,
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
) -> MediaAsset | None:
    """Persist a collector-generated crop from inside the configured data dir."""
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
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(extension)
        if mime_type is None:
            return None
        payload = source.read_bytes()
    except (OSError, ValueError):
        return None

    content_digest = hashlib.sha256(payload).hexdigest()
    source_url = f"prospect-crop:{content_digest}"
    existing = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.kind == "product",
            MediaAsset.master_product_id == product.id,
            MediaAsset.source_url == source_url,
        )
        .first()
    )
    if existing:
        existing.active = True
        _set_media_metadata(db, existing, media_source=media_source, audit_relevant=True)
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

    has_primary = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.kind == "product",
            MediaAsset.master_product_id == product.id,
            MediaAsset.active.is_(True),
            MediaAsset.is_primary.is_(True),
        )
        .first()
        is not None
    )
    asset = MediaAsset(
        kind="product",
        master_product_id=product.id,
        file_path=filename,
        source_url=source_url,
        alt_text=(alt_text or product.name)[:240],
        mime_type=mime_type,
        is_primary=not has_primary,
        active=True,
    )
    db.add(asset)
    db.flush()
    _set_media_metadata(db, asset, media_source=media_source, audit_relevant=True)
    _refresh_product_primary(db, product.id)
    return asset


def persist_collected_product_images(db: Session, rows) -> int:
    """Attach collector image URLs to the already-imported master products."""
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
        if not image_url and not image_path:
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
        if image_url:
            marker = (product.id, image_url)
            if marker not in handled:
                handled.add(marker)
                asset = persist_product_image(
                    db,
                    product,
                    image_url,
                    alt_text=getattr(row, "image_alt", None) or getattr(row, "product_name", None),
                    media_source=getattr(row, "image_media_source", None) or "retailer_cdn",
                    external_product_id=getattr(row, "lidl_product_id", None),
                    canonical_url=getattr(row, "canonical_url", None),
                )
                if asset:
                    saved += 1
        if image_path:
            marker = (product.id, image_path)
            if marker in handled:
                continue
            handled.add(marker)
            asset = persist_product_image_file(
                db,
                product,
                image_path,
                alt_text=getattr(row, "image_alt", None) or getattr(row, "product_name", None),
                media_source="prospect_crop",
            )
            if asset:
                saved += 1
    db.commit()
    return saved
