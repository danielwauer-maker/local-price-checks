from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy.orm import Session

from .collection_quality import CollectionQualitySnapshot
from .models import CollectionRun, Offer, Store


@dataclass(frozen=True)
class TargetMarket:
    key: str
    retailer: str
    city: str
    name_contains: str
    external_id: str | None = None


TARGET_MARKETS: tuple[TargetMarket, ...] = (
    TargetMarket("lidl-puderbach", "Lidl", "Puderbach", "Lidl"),
    TargetMarket("edeka-fellenzer-puderbach", "EDEKA", "Puderbach", "Fellenzer"),
    TargetMarket("aldi-dierdorf", "ALDI SÜD", "Dierdorf", "ALDI"),
    TargetMarket("netto-dierdorf", "Netto Marken-Discount", "Dierdorf", "Netto"),
    TargetMarket("rewe-hundertmark-dierdorf", "REWE", "Dierdorf", "REWE", "321019"),
    TargetMarket("aldi-oberhonnefeld", "ALDI SÜD", "Oberhonnefeld-Gierend", "ALDI"),
    TargetMarket("netto-oberhonnefeld", "Netto Marken-Discount", "Oberhonnefeld-Gierend", "Netto"),
)


@dataclass(frozen=True)
class StoreReadiness:
    target_key: str
    store_id: int | None
    store_name: str
    retailer: str
    city: str
    source_strategy: str
    status: str
    run_status: str | None = None
    quality_status: str | None = None
    benchmark_status: str | None = None
    benchmark_context: str | None = None
    external_validation_status: str | None = None
    external_validation_checked: int = 0
    quality_score: float | None = None
    offers_imported: int = 0
    reasons: tuple[str, ...] = ()

    @property
    def collector_primary(self) -> bool:
        return self.source_strategy == "collector_primary"


@dataclass(frozen=True)
class ExternalOfferSample:
    """Independent reference observation used to validate a collector result.

    References must describe a local stationary-market offer. `online_only=True`
    is intentionally supported so a benchmark can prove that such a reference
    was *not* imported by the local collector.
    """

    product_name: str
    brand: str | None = None
    variant: str | None = None
    package_size: str | None = None
    price: float | None = None
    unit_price: float | None = None
    unit_price_unit: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    image_expected: bool | None = None
    online_only: bool = False
    reference_id: str | None = None


@dataclass(frozen=True)
class SampleValidation:
    reference_id: str
    product_name: str
    matched: bool
    score: float
    matched_offer_id: int | None = None
    mismatches: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExternalValidationResult:
    score: float
    status: str
    checked: int
    matched: int
    missing: int
    online_only_leaks: int
    field_checks: int
    field_matches: int
    samples: tuple[SampleValidation, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["samples"] = [asdict(row) for row in self.samples]
        return payload


def _text(value: Any) -> str:
    value = str(value or "").strip().casefold()
    value = value.replace("ß", "ss")
    value = re.sub(r"[^a-z0-9äöü]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _same_number(left: Any, right: Any, tolerance: float = 0.011) -> bool:
    a, b = _float(left), _float(right)
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tolerance


def _offer_value(offer: Any, key: str, default: Any = None) -> Any:
    if isinstance(offer, Mapping):
        return offer.get(key, default)
    return getattr(offer, key, default)


def _offer_product_value(offer: Any, key: str, default: Any = None) -> Any:
    direct = _offer_value(offer, key, None)
    if direct is not None:
        return direct
    product = _offer_value(offer, "product", None)
    if isinstance(product, Mapping):
        return product.get(key, default)
    return getattr(product, key, default) if product is not None else default


def _name_similarity(reference: ExternalOfferSample, offer: Any) -> float:
    reference_name = _text(reference.product_name)
    offer_name = _text(_offer_product_value(offer, "name", _offer_value(offer, "product_name", "")))
    if not reference_name or not offer_name:
        return 0.0
    ratio = SequenceMatcher(None, reference_name, offer_name).ratio()
    ref_tokens, offer_tokens = set(reference_name.split()), set(offer_name.split())
    token_score = len(ref_tokens & offer_tokens) / max(1, len(ref_tokens | offer_tokens))
    brand = _text(reference.brand)
    offer_brand = _text(_offer_product_value(offer, "brand", ""))
    brand_bonus = 0.08 if brand and offer_brand and brand == offer_brand else 0.0
    return min(1.0, max(ratio, token_score) + brand_bonus)


def _best_offer(reference: ExternalOfferSample, offers: Sequence[Any], used: set[int]) -> tuple[int, Any] | None:
    ranked: list[tuple[float, int, Any]] = []
    for idx, offer in enumerate(offers):
        if idx in used:
            continue
        similarity = _name_similarity(reference, offer)
        if similarity >= 0.60:
            ranked.append((similarity, idx, offer))
    if not ranked:
        return None
    _score, idx, offer = max(ranked, key=lambda row: row[0])
    return idx, offer


def validate_external_samples(
    references: Sequence[ExternalOfferSample],
    offers: Sequence[Any],
    *,
    min_samples: int = 10,
) -> ExternalValidationResult:
    """Compare 10–20 independent spot checks with collected local offers.

    The function is deliberately data-source agnostic. A caller can feed ORM
    offers, dictionaries from a support export, or normalized collector rows.
    Online-only reference rows are negative controls: finding them in the local
    offer set is counted as a leak.
    """

    used: set[int] = set()
    rows: list[SampleValidation] = []
    matched = missing = online_only_leaks = field_checks = field_matches = 0

    for sample_no, reference in enumerate(references, start=1):
        reference_id = reference.reference_id or f"sample-{sample_no}"
        candidate = _best_offer(reference, offers, used)
        if reference.online_only:
            leaked = candidate is not None
            if leaked:
                online_only_leaks += 1
            rows.append(
                SampleValidation(
                    reference_id=reference_id,
                    product_name=reference.product_name,
                    matched=not leaked,
                    score=0.0 if leaked else 100.0,
                    matched_offer_id=_offer_value(candidate[1], "id") if candidate else None,
                    mismatches=("online_only_imported",) if leaked else (),
                )
            )
            continue

        if candidate is None:
            missing += 1
            rows.append(
                SampleValidation(
                    reference_id=reference_id,
                    product_name=reference.product_name,
                    matched=False,
                    score=0.0,
                    mismatches=("offer_missing",),
                )
            )
            continue

        idx, offer = candidate
        used.add(idx)
        mismatches: list[str] = []
        checks = matches = 1

        def check_text(field_name: str, expected: str | None, actual: Any) -> None:
            nonlocal checks, matches
            if expected is None:
                return
            checks += 1
            if _text(expected) == _text(actual):
                matches += 1
            else:
                mismatches.append(field_name)

        def check_number(field_name: str, expected: float | None, actual: Any) -> None:
            nonlocal checks, matches
            if expected is None:
                return
            checks += 1
            if _same_number(expected, actual):
                matches += 1
            else:
                mismatches.append(field_name)

        check_text("brand", reference.brand, _offer_product_value(offer, "brand"))
        check_text("package_size", reference.package_size, _offer_product_value(offer, "package_size"))
        check_number("price", reference.price, _offer_value(offer, "price"))
        check_number("unit_price", reference.unit_price, _offer_value(offer, "unit_price"))
        check_text("unit_price_unit", reference.unit_price_unit, _offer_value(offer, "unit_price_unit"))
        check_text("variant", reference.variant, _offer_value(offer, "variant"))

        for field_name, expected in (("valid_from", reference.valid_from), ("valid_to", reference.valid_to)):
            if expected is not None:
                checks += 1
                if _offer_value(offer, field_name) == expected:
                    matches += 1
                else:
                    mismatches.append(field_name)

        local_store_offer = _offer_value(offer, "local_store_offer", True)
        checks += 1
        if local_store_offer is True:
            matches += 1
        else:
            mismatches.append("not_local_store_offer")

        if reference.image_expected is True:
            checks += 1
            image_present = bool(
                _offer_value(offer, "image_url")
                or _offer_value(offer, "image_present")
                or _offer_product_value(offer, "image_url")
            )
            if image_present:
                matches += 1
            else:
                mismatches.append("image")

        field_checks += checks
        field_matches += matches
        matched += 1
        rows.append(
            SampleValidation(
                reference_id=reference_id,
                product_name=reference.product_name,
                matched=True,
                score=round(matches / checks * 100.0, 1),
                matched_offer_id=_offer_value(offer, "id"),
                mismatches=tuple(mismatches),
            )
        )

    positive_count = sum(1 for reference in references if not reference.online_only)
    identity_score = matched / positive_count * 100.0 if positive_count else 100.0
    detail_score = field_matches / field_checks * 100.0 if field_checks else 100.0
    leak_penalty = min(100.0, online_only_leaks * 25.0)
    score = round(max(0.0, identity_score * 0.60 + detail_score * 0.40 - leak_penalty), 1)
    positive_field_mismatch = any(
        row.mismatches
        for reference, row in zip(references, rows)
        if not reference.online_only and row.matched
    )

    if len(references) < min_samples:
        status = "INSUFFICIENT_SAMPLES"
    elif online_only_leaks or score < 90.0:
        status = "FAIL"
    elif score < 97.0 or missing or positive_field_mismatch:
        status = "WARN"
    else:
        status = "PASS"

    return ExternalValidationResult(
        score=score,
        status=status,
        checked=len(references),
        matched=matched,
        missing=missing,
        online_only_leaks=online_only_leaks,
        field_checks=field_checks,
        field_matches=field_matches,
        samples=tuple(rows),
    )


def persist_external_validation_result(
    db: Session,
    *,
    run: CollectionRun,
    result: ExternalValidationResult,
) -> CollectionQualitySnapshot:
    """Attach an independent external validation result to this exact collector run."""

    snapshot = _snapshot_for_run(db, run)
    if snapshot is None:
        raise ValueError("quality snapshot required before external validation can be persisted")
    metrics = _snapshot_metrics(snapshot)
    metrics.update(
        {
            "external_validation_status": result.status,
            "external_validation_score": result.score,
            "external_validation_checked": result.checked,
            "external_validation_matched": result.matched,
            "external_validation_missing": result.missing,
            "external_validation_online_only_leaks": result.online_only_leaks,
        }
    )
    snapshot.metrics_json = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    db.commit()
    return snapshot


def quality_metric_for_display(metrics: Mapping[str, Any], metric: str) -> float | int | str | None:
    """Return N/A semantics for diagnostics that were never applicable.

    Historic snapshots used numeric zero when a collector never emitted price
    anchor/page-recall diagnostics. That is different from an applicable check
    that genuinely measured 0 %. The explicit `*_applicable` flags win when
    present; old snapshots are inferred conservatively from diagnostic evidence.
    """

    if metric not in {"price_anchor_match_rate", "page_offer_recall"}:
        return metrics.get(metric)

    explicit = metrics.get(f"{metric}_applicable")
    if explicit is False:
        return None
    if explicit is True:
        return metrics.get(metric)

    diagnostic_evidence = any(
        int(metrics.get(key) or 0) > 0
        for key in (
            "price_anchors_detected",
            "price_anchors_matched",
            "price_anchors_ignored",
            "price_anchors_unmatched",
        )
    ) or bool(metrics.get("pages_with_unmatched_prices"))
    if not diagnostic_evidence:
        return None
    return metrics.get(metric)


def next_week_window(today: date) -> tuple[date, date]:
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    start = today + timedelta(days=days_until_monday)
    return start, start + timedelta(days=6)


def offer_covers_next_week(offer: Any, today: date) -> bool:
    week_start, week_end = next_week_window(today)
    valid_from = _offer_value(offer, "valid_from")
    valid_to = _offer_value(offer, "valid_to")
    if not isinstance(valid_from, date) or not isinstance(valid_to, date):
        return False
    return valid_from <= week_end and valid_to >= week_start


def _latest_run(db: Session, store_id: int) -> CollectionRun | None:
    return (
        db.query(CollectionRun)
        .filter(CollectionRun.store_id == store_id)
        .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        .first()
    )


def _snapshot_for_run(db: Session, run: CollectionRun | None) -> CollectionQualitySnapshot | None:
    if run is None:
        return None
    return (
        db.query(CollectionQualitySnapshot)
        .filter(CollectionQualitySnapshot.run_id == run.id)
        .first()
    )


def _snapshot_metrics(snapshot: CollectionQualitySnapshot | None) -> dict[str, Any]:
    if snapshot is None or not snapshot.metrics_json:
        return {}
    try:
        loaded = json.loads(snapshot.metrics_json)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _match_target(stores: Iterable[Store], target: TargetMarket) -> Store | None:
    candidates = [
        store
        for store in stores
        if store.retailer == target.retailer
        and _text(store.city) == _text(target.city)
        and _text(target.name_contains) in _text(store.name)
    ]
    if target.external_id:
        exact = [store for store in candidates if str(store.external_id or "") == target.external_id]
        return exact[0] if exact else None
    return candidates[0] if candidates else None


def assess_store_readiness(db: Session, target: TargetMarket, store: Store | None) -> StoreReadiness:
    if store is None:
        return StoreReadiness(
            target_key=target.key,
            store_id=None,
            store_name=target.name_contains,
            retailer=target.retailer,
            city=target.city,
            source_strategy="external_primary",
            status="MISSING_STORE",
            reasons=("target_store_not_configured",),
        )

    run = _latest_run(db, store.id)
    snapshot = _snapshot_for_run(db, run)
    metrics = _snapshot_metrics(snapshot)
    run_status = run.status if run else None
    quality_status = snapshot.quality_status if snapshot else None
    benchmark_status = snapshot.benchmark_status if snapshot else None
    benchmark_context = snapshot.benchmark_context if snapshot else None
    external_validation_status = str(metrics.get("external_validation_status") or "") or None
    try:
        external_validation_checked = int(metrics.get("external_validation_checked") or 0)
    except (TypeError, ValueError):
        external_validation_checked = 0
    reasons: list[str] = []

    if not store.active:
        reasons.append("store_inactive")
    if run is None:
        reasons.append("no_collection_run")
    elif run_status != "success":
        reasons.append("latest_run_not_success")
    if snapshot is None:
        reasons.append("no_quality_snapshot")
    else:
        if quality_status != "PASS":
            reasons.append("quality_not_pass")
        if benchmark_context != "PRODUCTION":
            reasons.append("benchmark_context_not_production")
        if benchmark_status != "PASS":
            reasons.append("benchmark_not_pass")
        if external_validation_status != "PASS":
            reasons.append("external_validation_not_pass")
        if external_validation_checked < 10:
            reasons.append("external_validation_insufficient_samples")

    collector_primary = bool(
        store.active
        and run_status == "success"
        and snapshot is not None
        and quality_status == "PASS"
        and benchmark_context == "PRODUCTION"
        and benchmark_status == "PASS"
        and external_validation_status == "PASS"
        and external_validation_checked >= 10
    )
    if collector_primary:
        strategy = "collector_primary"
        status = "READY"
    elif store.active:
        strategy = "external_primary"
        status = "VALIDATION_REQUIRED"
    else:
        strategy = "blocked"
        status = "BLOCKED"

    return StoreReadiness(
        target_key=target.key,
        store_id=store.id,
        store_name=store.name,
        retailer=store.retailer,
        city=store.city,
        source_strategy=strategy,
        status=status,
        run_status=run_status,
        quality_status=quality_status,
        benchmark_status=benchmark_status,
        benchmark_context=benchmark_context,
        external_validation_status=external_validation_status,
        external_validation_checked=external_validation_checked,
        quality_score=snapshot.quality_score if snapshot else None,
        offers_imported=int(run.offers_imported or 0) if run else 0,
        reasons=tuple(reasons),
    )


def build_multi_market_readiness(db: Session) -> dict[str, Any]:
    stores = db.query(Store).all()
    rows = [assess_store_readiness(db, target, _match_target(stores, target)) for target in TARGET_MARKETS]
    collector_primary = sum(1 for row in rows if row.collector_primary)
    return {
        "status": "READY" if collector_primary == len(TARGET_MARKETS) else "IN_PROGRESS",
        "collector_primary": collector_primary,
        "external_primary": sum(1 for row in rows if row.source_strategy == "external_primary"),
        "blocked": sum(1 for row in rows if row.source_strategy == "blocked"),
        "target_count": len(TARGET_MARKETS),
        "stores": [asdict(row) for row in rows],
    }


def next_week_offer_counts(db: Session, *, today: date) -> dict[int, int]:
    """Count already-imported offers overlapping the next Monday–Sunday window."""

    start, end = next_week_window(today)
    rows = (
        db.query(Offer.store_id, Offer.id)
        .filter(
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= end,
            Offer.valid_to >= start,
        )
        .all()
    )
    counts: dict[int, int] = {}
    for store_id, _offer_id in rows:
        counts[store_id] = counts.get(store_id, 0) + 1
    return counts
