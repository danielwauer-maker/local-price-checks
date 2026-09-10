from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import MEDIA_DIR, _admin, templates
from .db import get_db
from .models import MasterProduct, MediaAsset
from .product_media import preferred_product_media
from .product_media_admin import product_media_library, review_product_media, set_preferred_product_media
from .product_media_library import ProductMediaLibraryMetadata

router = APIRouter()


class ProductMediaReviewRequest(BaseModel):
    verification_status: str = "unreviewed"
    reason: str | None = None
    is_broken: bool | None = None
    is_placeholder: bool | None = None
    is_logo: bool | None = None


def _safe_return_to(value: str | None) -> str:
    if value and value.startswith("/admin/product-media-review") and "\n" not in value and "\r" not in value:
        return value
    return "/admin/product-media-review"


def _media_review_queue(
    db: Session,
    *,
    q: str = "",
    review_status: str = "unreviewed",
    issue: str = "all",
    limit: int = 200,
):
    query = (
        db.query(MediaAsset, MasterProduct, ProductMediaLibraryMetadata)
        .join(MasterProduct, MasterProduct.id == MediaAsset.master_product_id)
        .outerjoin(ProductMediaLibraryMetadata, ProductMediaLibraryMetadata.media_asset_id == MediaAsset.id)
        .filter(MediaAsset.kind == "product")
    )
    cleaned = q.strip()
    if cleaned:
        query = query.filter(MasterProduct.name.ilike(f"%{cleaned}%"))
    if review_status == "unreviewed":
        query = query.filter(or_(ProductMediaLibraryMetadata.id.is_(None), ProductMediaLibraryMetadata.verification_status == "unreviewed"))
    elif review_status in {"verified", "rejected"}:
        query = query.filter(ProductMediaLibraryMetadata.verification_status == review_status)
    if issue == "flagged":
        query = query.filter(or_(
            ProductMediaLibraryMetadata.is_broken.is_(True),
            ProductMediaLibraryMetadata.is_placeholder.is_(True),
            ProductMediaLibraryMetadata.is_logo.is_(True),
        ))
    elif issue == "low_quality":
        query = query.filter(ProductMediaLibraryMetadata.quality_score.is_not(None), ProductMediaLibraryMetadata.quality_score < 55)

    rows = query.order_by(
        ProductMediaLibraryMetadata.quality_score.asc().nullsfirst(),
        MediaAsset.created_at.desc(),
        MediaAsset.id.desc(),
    ).limit(max(1, min(limit, 500))).all()
    return [
        {"asset": asset, "product": product, "meta": meta}
        for asset, product, meta in rows
    ]


def _media_review_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(MediaAsset, ProductMediaLibraryMetadata)
        .outerjoin(ProductMediaLibraryMetadata, ProductMediaLibraryMetadata.media_asset_id == MediaAsset.id)
        .filter(MediaAsset.kind == "product")
        .all()
    )
    counts = {"total": len(rows), "unreviewed": 0, "verified": 0, "rejected": 0, "flagged": 0}
    for _, meta in rows:
        status = meta.verification_status if meta else "unreviewed"
        if status in counts:
            counts[status] += 1
        if meta and (meta.is_broken or meta.is_placeholder or meta.is_logo):
            counts["flagged"] += 1
    return counts


@router.get("/admin/product-media-review")
def admin_product_media_review_queue(
    request: Request,
    q: str = "",
    status: str = "unreviewed",
    issue: str = "all",
    limit: int = 200,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    if status not in {"all", "unreviewed", "verified", "rejected"}:
        status = "unreviewed"
    if issue not in {"all", "flagged", "low_quality"}:
        issue = "all"
    return templates.TemplateResponse("admin_product_media_review.html", {
        "request": request,
        "actor": actor,
        "admin_section": "product_media_review",
        "items": _media_review_queue(db, q=q, review_status=status, issue=issue, limit=limit),
        "counts": _media_review_counts(db),
        "q": q,
        "status": status,
        "issue": issue,
        "limit": max(1, min(limit, 500)),
    })


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
    return _serve_asset(row)


def _serve_asset(row: MediaAsset):
    if row.file_path:
        safe_name = Path(row.file_path).name
        target = MEDIA_DIR / safe_name
        if target.exists() and target.is_file():
            return FileResponse(target, media_type=row.mime_type or None)
    if row.source_url:
        return RedirectResponse(row.source_url, status_code=307)
    raise HTTPException(404, "Produktbild nicht verfügbar")


@router.get("/admin/product-media/{product_id}/{media_id}/preview")
def admin_product_media_preview(
    product_id: int,
    media_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    row = db.query(MediaAsset).filter(
        MediaAsset.id == media_id,
        MediaAsset.kind == "product",
        MediaAsset.master_product_id == product_id,
    ).first()
    if not row:
        raise HTTPException(404, "Produktbild nicht gefunden")
    return _serve_asset(row)


@router.get("/admin/product-media/{product_id}/library")
def admin_product_media_library(
    product_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
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
    row = _review(db, product_id, media_id, payload, actor)
    db.commit()
    return {"ok": True, "product_id": product_id, "media_id": media_id, "status": row.verification_status}


def _review(db: Session, product_id: int, media_id: int, payload: ProductMediaReviewRequest, actor: str):
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
    return row


@router.post("/admin/product-media-review/{product_id}/{media_id}/review")
def admin_review_product_media_form(
    product_id: int,
    media_id: int,
    verification_status: str = Form(...),
    reason: str = Form(""),
    is_broken: str = Form("0"),
    is_placeholder: str = Form("0"),
    is_logo: str = Form("0"),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    payload = ProductMediaReviewRequest(
        verification_status=verification_status,
        reason=reason.strip() or None,
        is_broken=is_broken == "1",
        is_placeholder=is_placeholder == "1",
        is_logo=is_logo == "1",
    )
    _review(db, product_id, media_id, payload, actor)
    db.commit()
    return RedirectResponse(_safe_return_to(return_to), status_code=303)


@router.post("/admin/product-media-review/{product_id}/{media_id}/preferred")
def admin_set_preferred_product_media_form(
    product_id: int,
    media_id: int,
    return_to: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    try:
        set_preferred_product_media(db, product_id, media_id, actor=actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, "product_media_preferred", "media", media_id, f"product_id={product_id}", actor)
    db.commit()
    return RedirectResponse(_safe_return_to(return_to), status_code=303)
