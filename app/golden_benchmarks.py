from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .engine_v140.collectors import CollectedOffer
from .engine_v140.product_cleaning import clean_product_name
from .extractor_adapter import (
    assess_collected_offer,
    package_size_label,
    prospect_page_from_text,
)


@dataclass(frozen=True)
class GoldenBenchmarkResult:
    retailer: str
    fixture: str
    precision: float
    recall: float
    provenance: float
    images: float
    package: float
    unit_price: float
    status: str
    failures: tuple[str, ...]


def _pct(value: int, total: int) -> float:
    return round(value / total * 100.0, 2) if total else 100.0


def _equal(left, right) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) < 0.011
    return left == right


def _observed(row: CollectedOffer) -> tuple[bool, dict]:
    assessment = assess_collected_offer(row)
    details = assessment.details
    return assessment.accepted, {
        "name": clean_product_name(row.product_name),
        "price": row.price,
        "package_size": details.package_label or package_size_label(row.quantity, row.unit),
        "unit_price": row.unit_price,
        "unit_price_unit": row.unit_price_unit,
        "page": prospect_page_from_text(row.source_text),
        "local": assessment.accepted,
        "image": bool(row.image_url),
        "regular_price": row.regular_price,
    }


def run_golden_benchmark(path: str | Path) -> GoldenBenchmarkResult:
    """Evaluate frozen retailer-adapter output against exact expected records."""

    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    true_positive = false_positive = false_negative = 0
    failures: list[str] = []
    positive_expected: list[dict] = []
    positive_observed: list[dict] = []

    for case in payload["cases"]:
        expected = case["expected"]
        expected_accepted = bool(expected["accepted"])
        row = CollectedOffer(**case["collected"])
        accepted, observed = _observed(row)
        if expected_accepted:
            positive_expected.append(expected)

        mismatches = [
            field
            for field, value in expected.items()
            if field != "accepted" and not _equal(observed.get(field), value)
        ]
        matched = accepted == expected_accepted and (not expected_accepted or not mismatches)
        if matched and expected_accepted:
            true_positive += 1
            positive_observed.append(observed)
        elif expected_accepted:
            false_negative += 1
            if accepted:
                false_positive += 1
            failures.append(f"{case['id']}: " + (", ".join(mismatches) or "rejected"))
        elif accepted:
            false_positive += 1
            failures.append(f"{case['id']}: unexpected local offer")

    precision = _pct(true_positive, true_positive + false_positive)
    recall = _pct(true_positive, true_positive + false_negative)
    expected_count = len(positive_expected)
    provenance = _pct(sum(1 for item in positive_observed if item["page"]), expected_count)
    images = _pct(sum(1 for item in positive_observed if item["image"]), expected_count)
    package = _pct(sum(1 for item in positive_observed if item["package_size"]), expected_count)
    unit_price = _pct(sum(1 for item in positive_observed if item["unit_price"]), expected_count)
    status = "PASS" if precision >= 99.0 and recall >= 99.0 else "FAIL"
    return GoldenBenchmarkResult(
        retailer=payload["retailer"],
        fixture=fixture_path.name,
        precision=precision,
        recall=recall,
        provenance=provenance,
        images=images,
        package=package,
        unit_price=unit_price,
        status=status,
        failures=tuple(failures),
    )
