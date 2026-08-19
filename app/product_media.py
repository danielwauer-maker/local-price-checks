from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import MasterProduct, MediaAsset

_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}


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
    return asset


def persist_collected_product_images(db: Session, rows) -> int:
    """Attach collector image URLs to the already-imported master products."""
    from .extractor_adapter import normalize_master_key

    saved = 0
    handled: set[tuple[int, str]] = set()
    for row in rows or []:
        image_url = (getattr(row, "image_url", None) or "").strip()
        if not image_url:
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
        marker = (product.id, image_url)
        if marker in handled:
            continue
        handled.add(marker)
        asset = persist_product_image(
            db,
            product,
            image_url,
            alt_text=getattr(row, "image_alt", None) or getattr(row, "product_name", None),
        )
        if asset:
            saved += 1
    db.commit()
    return saved
