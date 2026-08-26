from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from .collection_quality import CollectionQualitySnapshot
from .config import settings
from .coverage_models import StoreDiscoveryCandidate
from .db import Base
from .models import CollectionRun, Store


STORE_LIFECYCLE_STATUSES = (
    "discovered",
    "identity_verified",
    "promoted",
    "scrape_pending",
    "scrape_failed",
    "quality_review",
    "quality_passed",
    "public",
    "suspended",
)

QUALITY_CHECK_WEIGHTS = {
    "identity_verified": 15,
    "scrape_success": 20,
    "valid_offer_count": 20,
    "price_coverage": 20,
    "duplicate_rate": 10,
    "invalid_or_non_product_rate": 15,
}


class StoreActivationState(Base):
    __tablename__ = "store_activation_states"
    __table_args__ = (UniqueConstraint("store_id", name="uq_store_activation_state_store"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="promoted", index=True)
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    manually_suspended: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_runs.id"), nullable=True, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class StoreQualityAssessment(Base):
    __tablename__ = "store_quality_assessments"
    __table_args__ = (
        UniqueConstraint("collection_run_id", name="uq_store_quality_assessment_run"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    collection_run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    quality_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("collection_quality_snapshots.id"), index=True
    )
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    score: Mapped[float] = mapped_column(Float)
    checks_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text)
    failure_reasons_json: Mapped[str] = mapped_column(Text)
    warnings_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


@dataclass(frozen=True)
class StoreQualityResult:
    passed: bool
    score: float
    checks: dict[str, bool]
    metrics: dict
    failure_reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def _pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100.0, 1)


def activation_state(db: Session, store_id: int) -> StoreActivationState | None:
    return db.query(StoreActivationState).filter_by(store_id=store_id).first()


def ensure_activation_state(db: Session, store: Store) -> StoreActivationState:
    state = activation_state(db, store.id)
    if state is not None:
        return state
    if store.benchmark_verified and store.active:
        status, identity_verified, manually_suspended = "public", True, False
    elif not store.active:
        status, identity_verified, manually_suspended = "suspended", False, True
    else:
        status, identity_verified, manually_suspended = "promoted", False, False
    state = StoreActivationState(
        store_id=store.id,
        lifecycle_status=status,
        identity_verified=identity_verified,
        manually_suspended=manually_suspended,
        published_at=datetime.utcnow() if status == "public" else None,
        suspended_at=datetime.utcnow() if status == "suspended" else None,
    )
    db.add(state)
    db.flush()
    return state


def store_is_public(store: Store | None) -> bool:
    """Compatibility-safe public predicate used by all normal user flows."""
    return bool(store and store.active and store.benchmark_verified)


def _candidate_identity_verified(candidate: StoreDiscoveryCandidate) -> bool:
    return bool(
        candidate.matched_store_id
        and candidate.status == "promoted"
        and candidate.address_verified
        and candidate.coordinates_verified
        and candidate.official_source_verified
    )


def store_identity_verified(db: Session, store: Store) -> bool:
    state = activation_state(db, store.id)
    if state and state.identity_verified:
        return True
    candidates = db.query(StoreDiscoveryCandidate).filter_by(matched_store_id=store.id).all()
    return any(_candidate_identity_verified(candidate) for candidate in candidates)


def register_promoted_store(
    db: Session,
    store: Store,
    candidate: StoreDiscoveryCandidate,
) -> StoreActivationState:
    if not _candidate_identity_verified(candidate):
        raise ValueError("Marktidentität ist nicht vollständig bestätigt")
    state = ensure_activation_state(db, store)
    state.identity_verified = True
    state.manually_suspended = False
    state.suspension_reason = None
    if state.lifecycle_status != "public":
        state.lifecycle_status = "promoted"
    state.updated_at = datetime.utcnow()
    db.flush()
    return state


def can_start_test_scrape(db: Session, store: Store) -> bool:
    state = activation_state(db, store.id)
    return bool(
        state
        and state.identity_verified
        and store.active
        and not state.manually_suspended
        and state.lifecycle_status
        in {"promoted", "scrape_failed", "quality_review", "quality_passed"}
    )


def begin_test_scrape(db: Session, store: Store) -> StoreActivationState:
    if not can_start_test_scrape(db, store):
        raise ValueError("Test-Scrape erfordert einen promoteten, identitätsbestätigten Markt")
    state = activation_state(db, store.id)
    assert state is not None
    state.lifecycle_status = "scrape_pending"
    state.last_error = None
    state.updated_at = datetime.utcnow()
    db.commit()
    return state


def complete_test_scrape(db: Session, store: Store, run: CollectionRun) -> StoreActivationState:
    state = activation_state(db, store.id)
    if state is None or state.lifecycle_status != "scrape_pending":
        raise ValueError("Kein ausstehender Test-Scrape für diesen Markt")
    state.last_test_run_id = run.id
    if run.status == "success":
        state.lifecycle_status = "quality_review"
        state.last_error = None
    else:
        state.lifecycle_status = "scrape_failed"
        state.last_error = run.message or f"Collector-Status: {run.status}"
    state.updated_at = datetime.utcnow()
    db.commit()
    return state


def fail_test_scrape(
    db: Session,
    store: Store,
    *,
    run: CollectionRun | None = None,
    error: str,
) -> StoreActivationState:
    state = activation_state(db, store.id) or ensure_activation_state(db, store)
    state.lifecycle_status = "scrape_failed"
    state.last_test_run_id = run.id if run else state.last_test_run_id
    state.last_error = error[:1800]
    state.updated_at = datetime.utcnow()
    db.commit()
    return state


def assess_store_quality(
    *,
    identity_verified: bool,
    run: CollectionRun,
    snapshot: CollectionQualitySnapshot,
) -> StoreQualityResult:
    raw = json.loads(snapshot.metrics_json or "{}")
    raw_count = int(raw.get("raw_offer_count", run.offers_received) or 0)
    eligible_count = int(raw.get("eligible_offer_count", raw_count) or 0)
    valid_count = int(raw.get("valid_offer_count", run.offers_imported) or 0)
    with_price = int(raw.get("offers_with_price", valid_count) or 0)
    duplicates = int(raw.get("duplicate_count", 0) or 0)
    invalid_count = int(raw.get("invalid_or_non_product_count", 0) or 0)
    price_coverage = _pct(with_price, valid_count)
    duplicate_rate = _pct(duplicates, raw_count)
    invalid_rate = _pct(invalid_count, raw_count)
    duration_seconds = None
    if run.finished_at and run.started_at:
        duration_seconds = round(max(0.0, (run.finished_at - run.started_at).total_seconds()), 1)

    checks = {
        "identity_verified": bool(identity_verified),
        "scrape_success": run.status == "success",
        "valid_offer_count": valid_count >= settings.store_quality_min_valid_offers,
        "price_coverage": price_coverage >= settings.store_quality_min_price_coverage_pct,
        "duplicate_rate": duplicate_rate <= settings.store_quality_max_duplicate_rate_pct,
        "invalid_or_non_product_rate": invalid_rate <= settings.store_quality_max_invalid_rate_pct,
    }
    metrics = {
        "source_type": run.source_key,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": duration_seconds,
        "raw_offer_count": raw_count,
        "valid_offer_count": valid_count,
        "offers_with_price": with_price,
        "offers_with_unit_or_base_price": int(raw.get("offers_with_unit_or_base_price", 0) or 0),
        "duplicate_count": duplicates,
        "invalid_or_non_product_count": invalid_count,
        "price_coverage_pct": price_coverage,
        "duplicate_rate_pct": duplicate_rate,
        "invalid_or_non_product_rate_pct": invalid_rate,
        "prospect_date_available": bool(raw.get("prospect_date_available")),
        "prospect_page_available": bool(raw.get("prospect_page_available")),
        "collection_quality_status": snapshot.quality_status,
        "collection_quality_score": float(snapshot.quality_score),
    }
    failure_reasons: list[str] = []
    if not checks["identity_verified"]:
        failure_reasons.append("market_identity_not_verified")
    if not checks["scrape_success"]:
        failure_reasons.append(f"test_scrape_status_{run.status}")
    if not checks["valid_offer_count"]:
        failure_reasons.append(
            f"valid_offer_count_{valid_count}_below_{settings.store_quality_min_valid_offers}"
        )
    if not checks["price_coverage"]:
        failure_reasons.append(
            f"price_coverage_{price_coverage:.1f}_below_{settings.store_quality_min_price_coverage_pct:.1f}"
        )
    if not checks["duplicate_rate"]:
        failure_reasons.append(
            f"duplicate_rate_{duplicate_rate:.1f}_above_{settings.store_quality_max_duplicate_rate_pct:.1f}"
        )
    if not checks["invalid_or_non_product_rate"]:
        failure_reasons.append(
            f"invalid_rate_{invalid_rate:.1f}_above_{settings.store_quality_max_invalid_rate_pct:.1f}"
        )
    warnings: list[str] = []
    if snapshot.quality_status != "PASS":
        warnings.append(f"collection_quality_{snapshot.quality_status.lower()}")
    if not metrics["prospect_date_available"]:
        warnings.append("prospect_date_missing")
    if not metrics["prospect_page_available"]:
        warnings.append("prospect_page_missing")
    score = float(sum(weight for name, weight in QUALITY_CHECK_WEIGHTS.items() if checks[name]))
    return StoreQualityResult(
        passed=all(checks.values()),
        score=score,
        checks=checks,
        metrics=metrics,
        failure_reasons=tuple(failure_reasons),
        warnings=tuple(warnings),
    )


def result_from_assessment(row: StoreQualityAssessment) -> StoreQualityResult:
    return StoreQualityResult(
        passed=bool(row.passed),
        score=float(row.score),
        checks=json.loads(row.checks_json),
        metrics=json.loads(row.metrics_json),
        failure_reasons=tuple(json.loads(row.failure_reasons_json)),
        warnings=tuple(json.loads(row.warnings_json)),
    )


def latest_quality_assessment(db: Session, store_id: int) -> StoreQualityAssessment | None:
    return (
        db.query(StoreQualityAssessment)
        .filter_by(store_id=store_id)
        .order_by(StoreQualityAssessment.created_at.desc(), StoreQualityAssessment.id.desc())
        .first()
    )


def assess_latest_store_quality(db: Session, store: Store) -> StoreQualityResult:
    state = activation_state(db, store.id)
    if state is None or state.last_test_run_id is None:
        raise ValueError("Kein abgeschlossener Test-Scrape vorhanden")
    run = db.get(CollectionRun, state.last_test_run_id)
    snapshot = (
        db.query(CollectionQualitySnapshot)
        .filter_by(run_id=state.last_test_run_id, store_id=store.id)
        .first()
    )
    if run is None or snapshot is None:
        raise ValueError("Test-Scrape besitzt noch keine auswertbaren Qualitätsdaten")
    result = assess_store_quality(
        identity_verified=store_identity_verified(db, store),
        run=run,
        snapshot=snapshot,
    )
    assessment = db.query(StoreQualityAssessment).filter_by(collection_run_id=run.id).first()
    payload = {
        "passed": result.passed,
        "score": result.score,
        "checks_json": json.dumps(result.checks, ensure_ascii=False, sort_keys=True),
        "metrics_json": json.dumps(result.metrics, ensure_ascii=False, sort_keys=True),
        "failure_reasons_json": json.dumps(result.failure_reasons, ensure_ascii=False),
        "warnings_json": json.dumps(result.warnings, ensure_ascii=False),
    }
    if assessment is None:
        assessment = StoreQualityAssessment(
            store_id=store.id,
            collection_run_id=run.id,
            quality_snapshot_id=snapshot.id,
            **payload,
        )
        db.add(assessment)
    else:
        for key, value in payload.items():
            setattr(assessment, key, value)
        assessment.quality_snapshot_id = snapshot.id
        assessment.created_at = datetime.utcnow()
    state.lifecycle_status = "quality_passed" if result.passed else "quality_review"
    state.updated_at = datetime.utcnow()
    db.commit()
    return result


def store_ready_for_publication(
    db: Session,
    store: Store,
    quality_result: StoreQualityResult | None = None,
) -> bool:
    state = activation_state(db, store.id)
    if state is None or state.manually_suspended or state.lifecycle_status != "quality_passed":
        return False
    assessment = latest_quality_assessment(db, store.id)
    if quality_result is None:
        quality_result = result_from_assessment(assessment) if assessment else None
    return bool(
        state.identity_verified
        and state.last_test_run_id
        and assessment
        and assessment.collection_run_id == state.last_test_run_id
        and quality_result
        and quality_result.passed
    )


def publish_store(db: Session, store: Store) -> StoreActivationState:
    if not store_ready_for_publication(db, store):
        raise ValueError("Markt erfüllt das vollständige Public-Gate nicht")
    state = activation_state(db, store.id)
    assert state is not None
    store.active = True
    store.benchmark_verified = True
    state.lifecycle_status = "public"
    state.published_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    db.commit()
    return state


def suspend_store(db: Session, store: Store, reason: str) -> StoreActivationState:
    state = ensure_activation_state(db, store)
    state.lifecycle_status = "suspended"
    state.manually_suspended = True
    state.suspension_reason = reason.strip() or "manuell gesperrt"
    state.suspended_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    store.benchmark_verified = False
    db.commit()
    return state


def reactivate_store(db: Session, store: Store) -> StoreActivationState:
    state = activation_state(db, store.id)
    if state is None or not state.manually_suspended:
        raise ValueError("Markt ist nicht manuell gesperrt")
    state.manually_suspended = False
    state.suspension_reason = None
    state.suspended_at = None
    latest = latest_quality_assessment(db, store.id)
    latest_result = result_from_assessment(latest) if latest else None
    if latest_result and latest_result.passed and state.identity_verified:
        state.lifecycle_status = "quality_passed"
    else:
        state.lifecycle_status = "promoted"
    state.updated_at = datetime.utcnow()
    store.benchmark_verified = False
    db.commit()
    return state


def activation_overview(db: Session, store: Store) -> dict:
    state = activation_state(db, store.id)
    candidate = (
        db.query(StoreDiscoveryCandidate)
        .filter_by(matched_store_id=store.id)
        .order_by(StoreDiscoveryCandidate.updated_at.desc())
        .first()
    )
    run = db.get(CollectionRun, state.last_test_run_id) if state and state.last_test_run_id else None
    assessment = latest_quality_assessment(db, store.id)
    result = result_from_assessment(assessment) if assessment else None
    identity_verified = store_identity_verified(db, store)
    return {
        "state": state,
        "status": state.lifecycle_status if state else ("public" if store_is_public(store) else "promoted"),
        "identity_verified": identity_verified,
        "address_verified": bool(candidate and candidate.address_verified) or (
            store_is_public(store) and identity_verified
        ),
        "coordinates_verified": bool(candidate and candidate.coordinates_verified) or (
            store_is_public(store) and identity_verified
        ),
        "official_source_verified": bool(candidate and candidate.official_source_verified) or (
            store_is_public(store) and identity_verified
        ),
        "run": run,
        "quality": result,
        "is_public": store_is_public(store),
        "can_test_scrape": can_start_test_scrape(db, store),
        "can_assess_quality": bool(
            state and run and run.status == "success" and state.lifecycle_status == "quality_review"
        ),
        "can_publish": store_ready_for_publication(db, store),
        "can_suspend": store_is_public(store),
        "can_reactivate": bool(state and state.manually_suspended),
    }
