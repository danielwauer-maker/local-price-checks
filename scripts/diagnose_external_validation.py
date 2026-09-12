from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.db import SessionLocal
from app.production_readiness import _name_similarity, validate_external_samples
from scripts.validate_external_offers import (
    _latest_run,
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
        "occurrence_id": row.get("occurrence_id"),
        "occurrence_package_size": row.get("occurrence_package_size"),
        "occurrence_source_text": (row.get("occurrence_source_text") or "")[:700],
    }


def run_diagnostics(reference_path: Path) -> dict[str, Any]:
    payload = _load_payload(reference_path)
    references = _reference_samples(payload)

    db = SessionLocal()
    try:
        store = _target_store(db, payload)
        run, snapshot = _latest_run(db, store)
        start, end = _period(payload)
        offers = _offer_rows(db, store, start, end, run=run)
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
            matched_offer = next(
                (offer for offer in offers if offer.get("id") == matched_offer_id),
                None,
            )

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
                    "matched_offer_occurrence": (
                        {
                            "id": matched_offer.get("occurrence_id"),
                            "package_size": matched_offer.get("occurrence_package_size"),
                            "unit_price": matched_offer.get("occurrence_unit_price"),
                            "unit_price_unit": matched_offer.get("occurrence_unit_price_unit"),
                            "detail_text": matched_offer.get("occurrence_detail_text"),
                            "source_url": matched_offer.get("occurrence_source_url"),
                            "source_text": (matched_offer.get("occurrence_source_text") or "")[:700],
                        }
                        if matched_offer is not None
                        else None
                    ),
                }
            )

        return {
            "target_store_id": store.id,
            "target_store": store.name,
            "run_id": run.id,
            "run_started_at": run.started_at,
            "run_finished_at": run.finished_at,
            "run_status": run.status,
            "quality_status": snapshot.quality_status,
            "benchmark_status": snapshot.benchmark_status,
            "benchmark_context": snapshot.benchmark_context,
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
