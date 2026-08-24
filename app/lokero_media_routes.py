from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import ProductAdminData, ProductCategory
from .product_media import preferred_product_media

router = APIRouter(prefix="/api/lokero", tags=["lokero-media"])
MEDIA_DIR = settings.data_dir / "admin_media"


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
            "icon": "tag",
            "count": int(row.product_count or 0),
        }
        for row in rows
    ]
