from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import joinedload

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.collection_quality import CollectionQualitySnapshot
from app.db import SessionLocal
from app.models import CollectionRun, MediaAsset, Offer, OfferOccurrence, Store
from app.production_readiness import (
    ExternalOfferSample,
    persist_external_validation_result,
    validate_external_samples,
)

_ALLOWED_SAMPLE_FIELDS = {
    "product_name",
    "brand",
    "variant",
    "package_size",
    "price",
    "unit_price",
    "unit_price_unit",
    "valid_from",
    "valid_to",
    "image_expected",
    "online_only",
    "reference_id",
}


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("reference file must contain one JSON object")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("reference file must contain a non-empty samples list")
    return payload


def _reference_samples(payload: dict[str, Any]) -> list[ExternalOfferSample]:
    references: list[ExternalOfferSample] = []
    for index, raw in enumerate(payload["samples"], start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"sample {index} must be a JSON object")
        kwargs = {key: raw.get(key) for key in _ALLOWED_SAMPLE_FIELDS if key in raw}
        kwargs["valid_from"] = _parse_date(kwargs.get("valid_from"))
        kwargs["valid_to"] = _parse_date(kwargs.get("valid_to"))
        if not str(kwargs.get("product_name") or "").strip():
            raise ValueError(f"sample {index} has no product_name")
        references.append(ExternalOfferSample(**kwargs))
    return references


def _target_store(db, payload: dict[str, Any]) -> Store:
    target = payload.get("target") or {}
    retailer = str(target.get("retailer") or "").strip()
    city = str(target.get("city") or "").strip()
    name_contains = str(target.get("name_contains") or "").strip()
    external_id = str(target.get("external_id") or "").strip()
    if not retailer or not city or not name_contains:
        raise ValueError("target requires retailer, city and name_contains")

    query = db.query(Store).filter(Store.retailer == retailer, Store.city == city)
    candidates = [row for row in query.all() if name_contains.casefold() in row.name.casefold()]
    if external_id:
        candidates = [row for row in candidates if str(row.external_id or "") == external_id]
    if len(candidates) != 1:
        raise ValueError(f"target must resolve to exactly one store, got {len(candidates)}")
    return candidates[0]


def _latest_run(db, store: Store) -> tuple[CollectionRun, CollectionQualitySnapshot]:
    run = (
        db.query(CollectionRun)
        .filter(CollectionRun.store_id == store.id)
        .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        .first()
    )
    if run is None:
        raise ValueError("target store has no collection run")
    snapshot = (
        db.query(CollectionQualitySnapshot)
        .filter(CollectionQualitySnapshot.run_id == run.id)
        .first()
    )
    if snapshot is None:
        raise ValueError("latest collection run has no quality snapshot")
    if run.status != "success":
        raise ValueError(f"latest run is not successful: {run.status}")
    if snapshot.quality_status != "PASS":
        raise ValueError(f"latest run quality is not PASS: {snapshot.quality_status}")
    if snapshot.benchmark_context != "PRODUCTION":
        raise ValueError(f"latest run benchmark context is not PRODUCTION: {snapshot.benchmark_context}")
    if snapshot.benchmark_status != "PASS":
        raise ValueError(f"latest run benchmark is not PASS: {snapshot.benchmark_status}")
    return run, snapshot


def _period(payload: dict[str, Any]) -> tuple[date, date]:
    period = payload.get("period") or {}
    start = _parse_date(period.get("start"))
    end = _parse_date(period.get("end"))
    if start is None or end is None or end < start:
        raise ValueError("period requires a valid ISO start/end range")
    return start, end


def _offer_rows(
    db,
    store: Store,
    start: date,
    end: date,
    *,
    run: CollectionRun,
) -> list[dict[str, Any]]:
    if run.store_id != store.id:
        raise ValueError("collection run does not belong to target store")
    if run.started_at is None or run.finished_at is None:
        raise ValueError("collection run requires a completed time window")

    occurrences = (
        db.query(OfferOccurrence)
        .join(Offer, OfferOccurrence.offer_id == Offer.id)
        .options(joinedload(OfferOccurrence.offer).joinedload(Offer.product))
        .filter(
            Offer.store_id == store.id,
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= end,
            Offer.valid_to >= start,
            OfferOccurrence.collected_at >= run.started_at,
            OfferOccurrence.collected_at <= run.finished_at,
        )
        .order_by(OfferOccurrence.collected_at.desc(), OfferOccurrence.id.desc())
        .all()
    )
    latest_occurrence_by_offer: dict[int, OfferOccurrence] = {}
    for occurrence in occurrences:
        latest_occurrence_by_offer.setdefault(occurrence.offer_id, occurrence)
    offers = [occurrence.offer for occurrence in latest_occurrence_by_offer.values()]
    product_ids = {row.master_product_id for row in offers}
    image_product_ids = {
        row.master_product_id
        for row in db.query(MediaAsset).filter(
            MediaAsset.kind == "product",
            MediaAsset.active.is_(True),
            MediaAsset.master_product_id.in_(product_ids),
        )
        if row.master_product_id is not None
    } if product_ids else set()

    return [
        {
            "id": offer.id,
            "product_name": offer.product.name,
            "brand": offer.product.brand,
            "package_size": (
                offer.product.package_size
                or latest_occurrence_by_offer[offer.id].package_size
            ),
            "price": offer.price,
            "unit_price": offer.unit_price,
            "unit_price_unit": offer.unit_price_unit,
            "valid_from": offer.valid_from,
            "valid_to": offer.valid_to,
            "local_store_offer": offer.local_store_offer,
            "image_present": offer.master_product_id in image_product_ids,
            "occurrence_id": latest_occurrence_by_offer[offer.id].id,
            "occurrence_package_size": latest_occurrence_by_offer[offer.id].package_size,
            "occurrence_unit_price": latest_occurrence_by_offer[offer.id].unit_price,
            "occurrence_unit_price_unit": latest_occurrence_by_offer[offer.id].unit_price_unit,
            "occurrence_detail_text": latest_occurrence_by_offer[offer.id].detail_text,
            "occurrence_source_url": latest_occurrence_by_offer[offer.id].source_url,
            "occurrence_source_text": latest_occurrence_by_offer[offer.id].source_text,
        }
        for offer in offers
    ]


def run_validation(reference_path: Path, *, persist: bool = False) -> dict[str, Any]:
    payload = _load_payload(reference_path)
    references = _reference_samples(payload)
    if len(references) < 10:
        raise ValueError("at least 10 independent reference samples are required")

    db = SessionLocal()
    try:
        store = _target_store(db, payload)
        run, snapshot = _latest_run(db, store)
        start, end = _period(payload)
        offers = _offer_rows(db, store, start, end, run=run)
        result = validate_external_samples(references, offers, min_samples=10)
        if persist:
            persist_external_validation_result(db, run=run, result=result)

        report = {
            "target_store_id": store.id,
            "target_store": store.name,
            "run_id": run.id,
            "run_started_at": run.started_at.isoformat() if run.started_at else None,
            "run_status": run.status,
            "quality_status": snapshot.quality_status,
            "benchmark_status": snapshot.benchmark_status,
            "benchmark_context": snapshot.benchmark_context,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "offers_considered": len(offers),
            "persisted": persist,
            "external_validation": result.as_dict(),
            "evidence": payload.get("evidence", {}),
        }
        return report
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the latest successful production collector run against independent offer samples."
    )
    parser.add_argument("reference_file", type=Path)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Attach the validation result to the exact latest collection run's quality snapshot.",
    )
    args = parser.parse_args()

    try:
        report = run_validation(args.reference_file, persist=args.persist)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    status = report["external_validation"]["status"]
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
