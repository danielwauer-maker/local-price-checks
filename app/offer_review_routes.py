from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .clock import app_today
from .db import get_db
from .models import Offer
from .prospect_models import OfferProvenance, ProspectOfferReview

router = APIRouter(prefix="/api/offer-reviews", tags=["offer-review"])


class QuickReviewPayload(BaseModel):
    status: str


def _parse_market_ids(value: str) -> list[int]:
    result: list[int] = []
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            parsed = int(part)
        except ValueError:
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result


def _review_payload(provenance: OfferProvenance, review: ProspectOfferReview | None) -> dict:
    return {
        "productId": str(provenance.offer.master_product_id),
        "marketId": str(provenance.offer.store_id),
        "offerId": str(provenance.offer_id),
        "provenanceId": provenance.id,
        "prospectArchiveId": provenance.prospect_archive_id,
        "prospectPage": provenance.prospect_page,
        "sourceText": provenance.source_text,
        "reviewStatus": review.status if review else None,
        "reviewIssueType": review.issue_type if review else None,
        "reviewNotes": review.notes if review else None,
    }


@router.get("")
def offer_review_metadata(market_ids: str = "", db: Session = Depends(get_db)):
    """Return page provenance and review state for current concrete offers.

    The WebApp uses this only in its optional QA mode. Normal offer rendering
    remains driven by the existing bootstrap payload.
    """
    store_ids = _parse_market_ids(market_ids)
    if not store_ids:
        return []

    today = app_today()
    offers = (
        db.query(Offer)
        .filter(
            Offer.store_id.in_(store_ids),
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= today,
            Offer.valid_to >= today,
        )
        .all()
    )
    offer_ids = [row.id for row in offers]
    if not offer_ids:
        return []

    provenances = (
        db.query(OfferProvenance)
        .filter(OfferProvenance.offer_id.in_(offer_ids))
        .order_by(
            OfferProvenance.offer_id.asc(),
            OfferProvenance.collected_at.desc(),
            OfferProvenance.prospect_page.asc(),
        )
        .all()
    )

    # One concrete offer can occur on several prospect pages. The quick review
    # uses the newest archive occurrence as its primary target, while returning
    # all page numbers for the detail view.
    primary_by_offer: dict[int, OfferProvenance] = {}
    pages_by_offer: dict[int, list[int]] = {}
    for provenance in provenances:
        primary_by_offer.setdefault(provenance.offer_id, provenance)
        pages = pages_by_offer.setdefault(provenance.offer_id, [])
        if provenance.prospect_page not in pages:
            pages.append(provenance.prospect_page)

    primary_ids = [row.id for row in primary_by_offer.values()]
    reviews = {
        row.offer_provenance_id: row
        for row in db.query(ProspectOfferReview)
        .filter(ProspectOfferReview.offer_provenance_id.in_(primary_ids))
        .all()
    } if primary_ids else {}

    result = []
    for offer in offers:
        provenance = primary_by_offer.get(offer.id)
        if not provenance:
            result.append({
                "productId": str(offer.master_product_id),
                "marketId": str(offer.store_id),
                "offerId": str(offer.id),
                "provenanceId": None,
                "prospectArchiveId": None,
                "prospectPage": None,
                "prospectPages": [],
                "sourceText": None,
                "reviewStatus": None,
                "reviewIssueType": None,
                "reviewNotes": None,
            })
            continue
        payload = _review_payload(provenance, reviews.get(provenance.id))
        payload["prospectPages"] = sorted(pages_by_offer.get(offer.id, []))
        result.append(payload)
    return result


@router.put("/{provenance_id}")
def quick_review_offer(
    provenance_id: int,
    payload: QuickReviewPayload,
    db: Session = Depends(get_db),
):
    if payload.status not in {"correct", "incorrect"}:
        raise HTTPException(status_code=400, detail="status must be correct or incorrect")

    provenance = db.get(OfferProvenance, provenance_id)
    if not provenance:
        raise HTTPException(status_code=404, detail="Offer provenance not found")

    review = (
        db.query(ProspectOfferReview)
        .filter(ProspectOfferReview.offer_provenance_id == provenance_id)
        .first()
    )
    if not review:
        review = ProspectOfferReview(
            offer_provenance_id=provenance_id,
            reviewed_by="webapp-test",
        )
        db.add(review)

    was_quick_only = review.issue_type in {None, "webapp_flagged"} and not any(
        [
            review.expected_name,
            review.expected_brand,
            review.expected_package_size,
            review.expected_price is not None,
            review.notes,
        ]
    )

    review.status = payload.status
    if payload.status == "incorrect":
        if review.issue_type in {None, "webapp_flagged"}:
            review.issue_type = "webapp_flagged"
    elif was_quick_only:
        # Do not destroy a detailed correction that was already entered later
        # in Prospekt-Abgleich. Only clear the transient WebApp marker.
        review.issue_type = None

    if was_quick_only or review.reviewed_by == "webapp-test":
        review.reviewed_by = "webapp-test"
    review.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(review)

    result = _review_payload(provenance, review)
    result["prospectPages"] = [provenance.prospect_page]
    result["auditUrl"] = (
        f"/admin/articles/prospect-audit?store_id={provenance.offer.store_id}"
        f"&archive_id={provenance.prospect_archive_id}&page={provenance.prospect_page}"
    )
    return result
