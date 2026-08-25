from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from .models import Offer, OfferOccurrence, OfferPriceReference
from .prospect_models import OfferProvenance, ProspectOfferReview


OFFER_DELETE_BATCH_SIZE = 500


def delete_offer_graph(db: Session, offer_ids: Iterable[int]) -> dict[str, int]:
    """Delete offers and their complete dependent graph in FK-safe order.

    The cleanup is explicit so it also protects upgraded SQLite installations
    whose original foreign keys did not declare ``ON DELETE CASCADE``. Callers
    retain control of the surrounding transaction and commit.
    """

    ids = list(dict.fromkeys(offer_ids))
    result = {
        "offers": 0,
        "occurrences": 0,
        "price_references": 0,
        "provenance": 0,
        "reviews": 0,
    }
    for offset in range(0, len(ids), OFFER_DELETE_BATCH_SIZE):
        batch = ids[offset : offset + OFFER_DELETE_BATCH_SIZE]
        provenance_ids = [
            row[0]
            for row in db.query(OfferProvenance.id)
            .filter(OfferProvenance.offer_id.in_(batch))
            .all()
        ]
        if provenance_ids:
            result["reviews"] += (
                db.query(ProspectOfferReview)
                .filter(ProspectOfferReview.offer_provenance_id.in_(provenance_ids))
                .delete(synchronize_session=False)
            )
            result["provenance"] += (
                db.query(OfferProvenance)
                .filter(OfferProvenance.id.in_(provenance_ids))
                .delete(synchronize_session=False)
            )
        result["occurrences"] += (
            db.query(OfferOccurrence)
            .filter(OfferOccurrence.offer_id.in_(batch))
            .delete(synchronize_session=False)
        )
        result["price_references"] += (
            db.query(OfferPriceReference)
            .filter(OfferPriceReference.offer_id.in_(batch))
            .delete(synchronize_session=False)
        )
        result["offers"] += (
            db.query(Offer)
            .filter(Offer.id.in_(batch))
            .delete(synchronize_session=False)
        )
    return result
