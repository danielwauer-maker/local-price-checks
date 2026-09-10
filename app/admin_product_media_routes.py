from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import MEDIA_DIR, _admin
from .db import get_db
from .product_media import preferred_product_media
from .product_media_admin import product_media_library, review_product_media, set_preferred_product_media

router = APIRouter()


class ProductMediaReviewRequest(BaseModel):
    verification_status: str = "unreviewed"
    reason: str | None = None
    is_broken: bool | None = None
    is_placeholder: bool | None = None
    is_logo: bool | None = None


@router.get("/admin/product-media/{product_id}")
def admin_product_media(
    product_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    """Serve the existing audit-preferred product image."""
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


@router.get("/admin/product-media/{product_id}/library")
def admin_product_media_library(
    product_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    """Expose alternatives, provenance, quality and review state for BR-1E UI."""
    return {"product_id": product_id, "media": product_media_library(db, product_id)}


@router.post("/admin/product-media/{product_id}/{media_id}/preferred")
def admin_set_preferred_product_media(
    product_id: int,
    media_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    try:
        asset = set_preferred_product_media(db, product_id, media_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, "product_media_preferred", "media", media_id, f"product_id={product_id}", actor)
    db.commit()
    return {"ok": True, "product_id": product_id, "media_id": asset.id}


@router.post("/admin/product-media/{product_id}/{media_id}/review")
def admin_review_product_media(
    product_id: int,
    media_id: int,
    payload: ProductMediaReviewRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    try:
        row = review_product_media(
            db,
            product_id,
            media_id,
            verification_status=payload.verification_status,
            actor=actor,
            reason=payload.reason,
            is_broken=payload.is_broken,
            is_placeholder=payload.is_placeholder,
            is_logo=payload.is_logo,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(
        db,
        "product_media_reviewed",
        "media",
        media_id,
        f"product_id={product_id}; status={row.verification_status}; broken={bool(row.is_broken)}",
        actor,
    )
    db.commit()
    return {"ok": True, "product_id": product_id, "media_id": media_id, "status": row.verification_status}
