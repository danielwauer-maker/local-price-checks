from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import joinedload

from app.db import SessionLocal
from app.models import Offer, OfferOccurrence
from app.production_readiness import _name_similarity, validate_external_samples
from scripts.validate_external_offers import (
    _load_payload,
    _offer_rows,
    _period,
    _reference_samples,
    _target_store,
)


def _offer_summary(row: dict[str, Any], similarity: float) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "similarity": round(similarity, 3),
        "product_name": row.get("product_name"),
        "brand": row.get("brand"),
        "package_size": row.get("package_size"),
        "price": row.get("price"),
        "unit_price": row.get("unit_price"),
        "unit_price_unit": row.get("unit_price_unit"),
        "valid_from": row.get("valid_from"),
        "valid_to": row.get("valid_to"),
    }


def run_diagnostics(reference_path: Path) -> dict[str, Any]:
    payload = _load_payload(reference_path)
    references = _reference_samples(payload)

    db = SessionLocal()
    try:
        store = _target_store(db, payload)
        start, end = _period(payload)
        offers = _offer_rows(db, store, start, end)
        validation = validate_external_samples(references, offers, min_samples=10)

        matched_by_reference = {
            sample.reference_id: sample.matched_offer_id
            for sample in validation.samples
            if sample.matched_offer_id is not None
        }

        rows = []
        for reference in references:
            ranked = sorted(
                (
                    (_name_similarity(reference, offer), offer)
                    for offer in offers
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            top = [
                _offer_summary(offer, similarity)
                for similarity, offer in ranked[:5]
                if similarity > 0
            ]

            same_price = [
                _offer_summary(offer, _name_similarity(reference, offer))
                for offer in offers
                if reference.price is not None
                and offer.get("price") is not None
                and abs(float(offer["price"]) - float(reference.price)) <= 0.011
            ][:10]

            matched_offer_id = matched_by_reference.get(reference.reference_id or "")
            occurrence = None
            if matched_offer_id is not None:
                occ = (
                    db.query(OfferOccurrence)
                    .filter(OfferOccurrence.offer_id == matched_offer_id)
                    .order_by(OfferOccurrence.collected_at.desc(), OfferOccurrence.id.desc())
                    .first()
                )
                if occ is not None:
                    occurrence = {
                        "package_size": occ.package_size,
                        "unit_price": occ.unit_price,
                        "unit_price_unit": occ.unit_price_unit,
                        "detail_text": occ.detail_text,
                        "source_url": occ.source_url,
                        "source_text": (occ.source_text or "")[:700],
                    }

            rows.append(
                {
                    "reference_id": reference.reference_id,
                    "reference": {
                        "product_name": reference.product_name,
                        "brand": reference.brand,
                        "package_size": reference.package_size,
                        "price": reference.price,
                        "unit_price": reference.unit_price,
                        "unit_price_unit": reference.unit_price_unit,
                        "valid_to": reference.valid_to,
                    },
                    "validation": next(
                        (
                            sample.__dict__
                            for sample in validation.samples
                            if sample.reference_id == (reference.reference_id or "")
                        ),
                        None,
                    ),
                    "top_name_candidates": top,
                    "same_price_candidates": same_price,
                    "matched_offer_occurrence": occurrence,
                }
            )

        return {
            "target_store_id": store.id,
            "target_store": store.name,
            "period_start": start,
            "period_end": end,
            "offers_considered": len(offers),
            "validation": validation.as_dict(),
            "diagnostics": rows,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only diagnostics for external validation mismatches."
    )
    parser.add_argument("reference_file", type=Path)
    args = parser.parse_args()

    try:
        report = run_diagnostics(args.reference_file)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
