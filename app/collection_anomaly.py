from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from sqlalchemy.orm import Session

from .collection_quality import RETAILER_QUALITY_POLICIES
from .config import settings
from .models import CollectionRun, Store


@dataclass(frozen=True)
class CollapsePolicy:
    history_runs: int = 5
    minimum_history: int = 3
    warning_ratio: float = 0.70
    block_ratio: float = 0.40


@dataclass(frozen=True)
class CollapseAssessment:
    state: str
    candidate_count: int
    baseline: float | None
    ratio: float | None
    reason: str | None


DEFAULT_COLLAPSE_POLICY = CollapsePolicy(
    history_runs=settings.collector_collapse_history_runs,
    minimum_history=settings.collector_collapse_minimum_history,
    warning_ratio=settings.collector_collapse_warning_ratio,
    block_ratio=settings.collector_collapse_block_ratio,
)


def assess_offer_count(
    db: Session,
    *,
    store: Store,
    candidate_count: int,
    policy: CollapsePolicy = DEFAULT_COLLAPSE_POLICY,
    apply_retailer_floor: bool = True,
) -> CollapseAssessment:
    recent = [
        int(value)
        for (value,) in (
            db.query(CollectionRun.offers_imported)
            .filter(
                CollectionRun.store_id == store.id,
                CollectionRun.status == "success",
                CollectionRun.offers_imported > 0,
            )
            .order_by(CollectionRun.started_at.desc())
            .limit(policy.history_runs)
            .all()
        )
    ]
    baseline = float(median(recent)) if len(recent) >= policy.minimum_history else None
    ratio = float(candidate_count) / baseline if baseline else None
    historical_state = "healthy"
    if ratio is not None and ratio < policy.block_ratio:
        historical_state = "blocked"
    elif ratio is not None and ratio < policy.warning_ratio:
        historical_state = "warning"

    retailer_floor = RETAILER_QUALITY_POLICIES.get(store.retailer)
    floor_blocked = bool(
        apply_retailer_floor
        and baseline is not None
        and retailer_floor
        and candidate_count < retailer_floor.expected_min_offers * retailer_floor.fail_count_ratio
    )
    state = "blocked" if floor_blocked or historical_state == "blocked" else historical_state
    if state == "healthy":
        return CollapseAssessment(state, candidate_count, baseline, ratio, None)
    if baseline is not None and historical_state == "blocked":
        reason = f"offer_count_collapse: {candidate_count} vs recent median {baseline:g}"
    else:
        reason = (
            f"offer_count_below_retailer_floor: {candidate_count} vs expected "
            f"{retailer_floor.expected_min_offers if retailer_floor else 'unknown'}"
        )
    return CollapseAssessment(state, candidate_count, baseline, ratio, reason)
