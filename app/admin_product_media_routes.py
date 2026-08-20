from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from .admin_routes import MEDIA_DIR, _admin
from .db import get_db
from .product_media import preferred_product_media

router = APIRouter()


@router.get("/admin/product-media/{product_id}")
def admin_product_media(
    product_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    row = preferred_product_media(db, product_id, purpose="audit")
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
