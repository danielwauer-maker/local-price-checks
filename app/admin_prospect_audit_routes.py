from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import _admin
from .db import get_db
from .models import Store
from .prospect_models import (
    OfferProvenance,
    Prospect,
    ProspectArchive,
    ProspectMissingItem,
    ProspectOfferReview,
)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()

ISSUE_TYPES = [
    ("wrong_product", "Falscher Artikel"),
    ("missing_name", "Name fehlt/unvollständig"),
    ("missing_brand", "Marke fehlt/falsch"),
    ("missing_package", "Packungsgröße fehlt/falsch"),
    ("missing_price", "Preis fehlt"),
    ("wrong_price", "Preis falsch"),
    ("missing_unit_price", "Grundpreis fehlt/falsch"),
    ("wrong_page", "Falsche PDF-Seite"),
    ("other", "Sonstiger Fehler"),
]
ISSUE_LABELS = dict(ISSUE_TYPES)
REVIEW_FILTERS = {"all", "open", "errors", "correct"}


def _optional_positive_int(value: str | int | None) -> int | None:
    """Treat empty form/query values as unset instead of raising FastAPI 422."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = int(cleaned)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _redirect(store_id: int | None, archive_id: int | None, page: int | None = None) -> RedirectResponse:
    params = []
    if store_id:
        params.append(f"store_id={store_id}")
    if archive_id:
        params.append(f"archive_id={archive_id}")
    if page:
        params.append(f"page={page}")
    suffix = "?" + "&".join(params) if params else ""
    return RedirectResponse(f"/admin/articles/prospect-audit{suffix}", status_code=303)


def _archive_golden_stats(db: Session, archive_id: int) -> dict[str, int | float | bool]:
    """Return archive-wide manual QA completeness used as Golden Dataset gate.

    Reviewed incorrect rows are valid supervised correction examples and count as
    reviewed. An archive is Golden-ready once every extracted row was reviewed
    and no manually reported missing item is still unresolved.
    """
    provenance_ids = [
        row[0]
        for row in db.query(OfferProvenance.id)
        .filter(OfferProvenance.prospect_archive_id == archive_id)
        .all()
    ]
    total = len(provenance_ids)
    reviews = (
        db.query(ProspectOfferReview)
        .filter(ProspectOfferReview.offer_provenance_id.in_(provenance_ids))
        .all()
        if provenance_ids
        else []
    )
    reviewed = sum(1 for row in reviews if row.status in {"correct", "incorrect"})
    correct = sum(1 for row in reviews if row.status == "correct")
    incorrect = sum(1 for row in reviews if row.status == "incorrect")
    unresolved_missing = (
        db.query(ProspectMissingItem)
        .filter(
            ProspectMissingItem.prospect_archive_id == archive_id,
            ProspectMissingItem.resolved.is_(False),
        )
        .count()
    )
    open_count = max(total - reviewed, 0)
    completeness = round((reviewed / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "reviewed": reviewed,
        "correct": correct,
        "incorrect": incorrect,
        "open": open_count,
        "unresolved_missing": unresolved_missing,
        "completeness": completeness,
        "golden_ready": bool(total and open_count == 0 and unresolved_missing == 0),
    }


@router.get("/admin/articles/prospect-audit")
def prospect_article_audit(
    request: Request,
    store_id: str | None = None,
    archive_id: str | None = None,
    page: str | None = None,
    review_filter: str = "all",
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store_id_value = _optional_positive_int(store_id)
    archive_id_value = _optional_positive_int(archive_id)
    page_value = _optional_positive_int(page)
    if review_filter not in REVIEW_FILTERS:
        review_filter = "all"

    stores = db.query(Store).filter(Store.active.is_(True)).order_by(Store.retailer, Store.city, Store.name).all()
    selected_store = db.get(Store, store_id_value) if store_id_value else (stores[0] if stores else None)

    archives = []
    current = None
    nxt = None
    selected_archive = None
    rows = []
    reviews = {}
    missing_items = []
    page_numbers = []
    golden_stats = None

    if selected_store:
        archives = (
            db.query(ProspectArchive)
            .filter(ProspectArchive.store_id == selected_store.id)
            .order_by(ProspectArchive.valid_from.desc(), ProspectArchive.fetched_at.desc())
            .all()
        )
        current = db.query(Prospect).filter_by(store_id=selected_store.id, period_key="current", active=True).first()
        nxt = db.query(Prospect).filter_by(store_id=selected_store.id, period_key="next", active=True).first()

        if archive_id_value:
            selected_archive = db.get(ProspectArchive, archive_id_value)
            if selected_archive and selected_archive.store_id != selected_store.id:
                selected_archive = None
        if not selected_archive and archives:
            selected_archive = archives[0]

    if selected_archive:
        golden_stats = _archive_golden_stats(db, selected_archive.id)
        query = (
            db.query(OfferProvenance)
            .filter(OfferProvenance.prospect_archive_id == selected_archive.id)
            .order_by(OfferProvenance.prospect_page.asc(), OfferProvenance.id.asc())
        )
        if page_value:
            query = query.filter(OfferProvenance.prospect_page == page_value)
        rows = query.all()
        provenance_ids = [row.id for row in rows]
        if provenance_ids:
            reviews = {
                row.offer_provenance_id: row
                for row in db.query(ProspectOfferReview)
                .filter(ProspectOfferReview.offer_provenance_id.in_(provenance_ids))
                .all()
            }
        missing_q = db.query(ProspectMissingItem).filter(ProspectMissingItem.prospect_archive_id == selected_archive.id)
        if page_value:
            missing_q = missing_q.filter(ProspectMissingItem.prospect_page == page_value)
        missing_items = missing_q.order_by(ProspectMissingItem.prospect_page, ProspectMissingItem.id).all()
        page_numbers = sorted({row.prospect_page for row in rows} | {row.prospect_page for row in missing_items})
        if selected_archive.page_count:
            page_numbers = list(range(1, selected_archive.page_count + 1))

    page_total = len(rows)
    reviewed = sum(1 for row in rows if row.id in reviews)
    correct = sum(1 for row in rows if reviews.get(row.id) and reviews[row.id].status == "correct")
    incorrect = sum(1 for row in rows if reviews.get(row.id) and reviews[row.id].status == "incorrect")

    if review_filter == "open":
        rows = [row for row in rows if row.id not in reviews]
    elif review_filter == "errors":
        rows = [row for row in rows if reviews.get(row.id) and reviews[row.id].status == "incorrect"]
    elif review_filter == "correct":
        rows = [row for row in rows if reviews.get(row.id) and reviews[row.id].status == "correct"]

    return templates.TemplateResponse(
        "admin_prospect_audit.html",
        {
            "request": request,
            "actor": actor,
            "stores": stores,
            "selected_store": selected_store,
            "archives": archives,
            "selected_archive": selected_archive,
            "current": current,
            "next": nxt,
            "rows": rows,
            "reviews": reviews,
            "missing_items": missing_items,
            "issue_types": ISSUE_TYPES,
            "page_numbers": page_numbers,
            "page": page_value,
            "review_filter": review_filter,
            "golden_stats": golden_stats,
            "stats": {
                "total": page_total,
                "reviewed": reviewed,
                "correct": correct,
                "incorrect": incorrect,
                "missing": len(missing_items),
                "visible": len(rows),
            },
        },
    )


@router.get("/admin/articles/prospect-audit/errors")
def prospect_error_inbox(
    request: Request,
    store_id: str | None = None,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    """Central inbox for all manual QA problems that still need attention."""
    store_id_value = _optional_positive_int(store_id)
    stores = db.query(Store).filter(Store.active.is_(True)).order_by(Store.retailer, Store.city, Store.name).all()

    incorrect_query = (
        db.query(ProspectOfferReview)
        .join(OfferProvenance, ProspectOfferReview.offer_provenance_id == OfferProvenance.id)
        .join(ProspectArchive, OfferProvenance.prospect_archive_id == ProspectArchive.id)
        .filter(ProspectOfferReview.status == "incorrect")
    )
    missing_query = (
        db.query(ProspectMissingItem)
        .join(ProspectArchive, ProspectMissingItem.prospect_archive_id == ProspectArchive.id)
        .filter(ProspectMissingItem.resolved.is_(False))
    )
    if store_id_value:
        incorrect_query = incorrect_query.filter(ProspectArchive.store_id == store_id_value)
        missing_query = missing_query.filter(ProspectArchive.store_id == store_id_value)

    incorrect_rows = incorrect_query.order_by(ProspectOfferReview.reviewed_at.desc()).all()
    missing_rows = missing_query.order_by(ProspectMissingItem.created_at.desc()).all()
    issue_counts = Counter(row.issue_type or "other" for row in incorrect_rows)

    return templates.TemplateResponse(
        "admin_prospect_errors.html",
        {
            "request": request,
            "actor": actor,
            "admin_section": "prospect_errors",
            "stores": stores,
            "selected_store_id": store_id_value,
            "incorrect_rows": incorrect_rows,
            "missing_rows": missing_rows,
            "issue_counts": issue_counts,
            "issue_labels": ISSUE_LABELS,
            "stats": {
                "incorrect": len(incorrect_rows),
                "missing": len(missing_rows),
                "total": len(incorrect_rows) + len(missing_rows),
            },
        },
    )


@router.get("/admin/prospect-archive/{archive_id}/pdf")
def archived_prospect_pdf(
    archive_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    row = db.get(ProspectArchive, archive_id)
    if not row or not row.pdf_bytes:
        raise HTTPException(404, "Archived prospect PDF not found")
    filename = row.original_filename or f"prospekt-{row.store_id}-{row.id}.pdf"
    return Response(
        content=row.pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/admin/articles/prospect-audit/{provenance_id}/quick-correct")
def quick_correct_offer(
    provenance_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    """One-click/checkbox approval for the fast Golden Dataset review flow."""
    provenance = db.get(OfferProvenance, provenance_id)
    if not provenance:
        raise HTTPException(404, "Offer provenance not found")
    row = db.query(ProspectOfferReview).filter_by(offer_provenance_id=provenance_id).first()
    if not row:
        row = ProspectOfferReview(offer_provenance_id=provenance_id)
        db.add(row)
    row.status = "correct"
    row.issue_type = None
    row.expected_name = None
    row.expected_brand = None
    row.expected_package_size = None
    row.expected_price = None
    row.notes = None
    row.reviewed_by = actor
    row.reviewed_at = datetime.utcnow()
    audit(
        db,
        "prospect_offer_quick_correct",
        "offer_provenance",
        provenance.id,
        f"archive={provenance.prospect_archive_id}; page={provenance.prospect_page}",
        actor,
    )
    db.commit()
    return _redirect(provenance.prospect_archive.store_id, provenance.prospect_archive_id, provenance.prospect_page)


@router.post("/admin/articles/prospect-audit/{provenance_id}/review")
def save_offer_review(
    provenance_id: int,
    status: str = Form(...),
    issue_type: str = Form(""),
    expected_name: str = Form(""),
    expected_brand: str = Form(""),
    expected_package_size: str = Form(""),
    expected_price: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    provenance = db.get(OfferProvenance, provenance_id)
    if not provenance:
        raise HTTPException(404, "Offer provenance not found")
    if status not in {"correct", "incorrect"}:
        raise HTTPException(400, "Invalid review status")

    row = db.query(ProspectOfferReview).filter_by(offer_provenance_id=provenance_id).first()
    if not row:
        row = ProspectOfferReview(offer_provenance_id=provenance_id)
        db.add(row)
    row.status = status
    row.issue_type = issue_type or None
    row.expected_name = expected_name.strip() or None
    row.expected_brand = expected_brand.strip() or None
    row.expected_package_size = expected_package_size.strip() or None
    try:
        row.expected_price = float(expected_price.replace(",", ".")) if expected_price.strip() else None
    except ValueError:
        row.expected_price = None
    row.notes = notes.strip() or None
    row.reviewed_by = actor
    row.reviewed_at = datetime.utcnow()

    audit(
        db,
        "prospect_offer_reviewed",
        "offer_provenance",
        provenance.id,
        f"status={status}; issue={row.issue_type or '-'}; archive={provenance.prospect_archive_id}; page={provenance.prospect_page}",
        actor,
    )
    db.commit()
    return _redirect(provenance.prospect_archive.store_id, provenance.prospect_archive_id, provenance.prospect_page)


@router.post("/admin/articles/prospect-audit/{archive_id}/missing")
def report_missing_item(
    archive_id: int,
    prospect_page: int = Form(...),
    expected_name: str = Form(...),
    expected_brand: str = Form(""),
    expected_package_size: str = Form(""),
    expected_price: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    archive = db.get(ProspectArchive, archive_id)
    if not archive:
        raise HTTPException(404, "Prospect archive not found")
    if prospect_page < 1 or (archive.page_count and prospect_page > archive.page_count):
        raise HTTPException(400, "Invalid prospect page")
    try:
        price = float(expected_price.replace(",", ".")) if expected_price.strip() else None
    except ValueError:
        price = None

    row = ProspectMissingItem(
        prospect_archive_id=archive.id,
        prospect_page=prospect_page,
        expected_name=expected_name.strip(),
        expected_brand=expected_brand.strip() or None,
        expected_package_size=expected_package_size.strip() or None,
        expected_price=price,
        notes=notes.strip() or None,
        reported_by=actor,
    )
    db.add(row)
    audit(db, "prospect_item_missing", "prospect_archive", archive.id, f"page={prospect_page}; name={row.expected_name}", actor)
    db.commit()
    return _redirect(archive.store_id, archive.id, prospect_page)


@router.post("/admin/articles/prospect-audit/missing/{missing_id}/resolve")
def resolve_missing_item(
    missing_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    row = db.get(ProspectMissingItem, missing_id)
    if not row:
        raise HTTPException(404, "Missing-item feedback not found")
    row.resolved = not row.resolved
    audit(db, "prospect_missing_item_resolved", "prospect_missing_item", row.id, f"resolved={row.resolved}", actor)
    db.commit()
    return _redirect(row.prospect_archive.store_id, row.prospect_archive_id, row.prospect_page)
