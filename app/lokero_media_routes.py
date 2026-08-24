from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .db import get_db
from .models import Offer, ProductAdminData, ProductCategory, Store
from .product_media import preferred_product_media

router = APIRouter(prefix="/api/lokero", tags=["lokero-media"])
MEDIA_DIR = settings.data_dir / "admin_media"

CATEGORY_ICONS = {
    "obst-gemuese": "apple",
    "fleisch-wurst": "beef",
    "fisch": "fish",
    "kaese": "cheese",
    "molkerei": "milk",
    "brot": "bread",
    "getraenke": "drink",
    "suesswaren": "candy",
    "tiefkuehl": "snow",
    "vorrat": "wheat",
    "fruehstueck": "coffee",
    "fertiggerichte": "soup",
    "drogerie": "sparkles",
    "haushalt": "home",
    "tiernahrung": "package",
    "sonstiges": "package",
}


def _asset_is_serveable(asset) -> bool:
    if not asset:
        return False
    if asset.file_path:
        target = MEDIA_DIR / Path(asset.file_path).name
        if target.exists() and target.is_file():
            return True
    return bool(asset.source_url and asset.source_url.lower().startswith(("http://", "https://")))


@router.get("/product-media/{product_id}")
def product_media(product_id: int, db: Session = Depends(get_db)):
    asset = preferred_product_media(db, product_id, purpose="public")
    if not asset:
        raise HTTPException(status_code=404, detail="No product image")

    if asset.file_path:
        safe_name = Path(asset.file_path).name
        target = MEDIA_DIR / safe_name
        if target.exists() and target.is_file():
            return FileResponse(target, media_type=asset.mime_type or None)

    if asset.source_url and asset.source_url.lower().startswith(("http://", "https://")):
        return RedirectResponse(asset.source_url, status_code=307)

    raise HTTPException(status_code=404, detail="Product image unavailable")


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = (
        db.query(
            ProductCategory.id,
            ProductCategory.name,
            ProductCategory.slug,
            ProductCategory.sort_order,
            func.count(ProductAdminData.id).label("product_count"),
        )
        .outerjoin(ProductAdminData, ProductAdminData.category_id == ProductCategory.id)
        .filter(ProductCategory.active.is_(True))
        .group_by(ProductCategory.id)
        .order_by(ProductCategory.sort_order.asc(), ProductCategory.name.asc())
        .all()
    )
    return [
        {
            "id": row.slug,
            "label": row.name,
            "icon": CATEGORY_ICONS.get(row.slug, "package"),
            "count": int(row.product_count or 0),
        }
        for row in rows
    ]


@router.get("/media-coverage")
def media_coverage(db: Session = Depends(get_db)):
    """Report actually serveable image coverage for current public offers."""
    today = app_today()
    product_ids = [
        row[0]
        for row in (
            db.query(Offer.master_product_id)
            .join(Store, Store.id == Offer.store_id)
            .filter(
                Store.active.is_(True),
                Store.benchmark_verified.is_(True),
                Offer.valid_from <= today,
                Offer.valid_to >= today,
                Offer.local_store_offer.is_(True),
            )
            .distinct()
            .all()
        )
    ]

    with_media: list[int] = []
    missing: list[int] = []
    for product_id in product_ids:
        asset = preferred_product_media(db, product_id, purpose="public")
        if _asset_is_serveable(asset):
            with_media.append(product_id)
        else:
            missing.append(product_id)

    total = len(product_ids)
    covered = len(with_media)
    return {
        "currentPublicProducts": total,
        "withPublicMedia": covered,
        "missingPublicMedia": len(missing),
        "coveragePercentage": round((covered / total * 100.0), 1) if total else 100.0,
        "missingProductIds": missing[:200],
    }
