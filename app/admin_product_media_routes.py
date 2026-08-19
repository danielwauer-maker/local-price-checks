from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from .admin_routes import MEDIA_DIR, _admin
from .db import get_db
from .models import MediaAsset

router = APIRouter()


@router.get("/admin/product-media/{product_id}")
def admin_product_media(
    product_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    row = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.kind == "product",
            MediaAsset.master_product_id == product_id,
            MediaAsset.active.is_(True),
        )
        .order_by(MediaAsset.is_primary.desc(), MediaAsset.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(404, "Kein Produktbild hinterlegt")

    if row.file_path:
        safe_name = Path(row.file_path).name
        target = MEDIA_DIR / safe_name
        if target.exists() and target.is_file():
            return FileResponse(target, media_type=row.mime_type or None)

    if row.source_url:
        return RedirectResponse(row.source_url, status_code=307)

    raise HTTPException(404, "Produktbild nicht verfügbar")
