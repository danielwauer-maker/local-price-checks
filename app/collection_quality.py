from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base
from .models import CollectionRun, MasterProduct, MediaAsset, Offer, OfferOccurrence, Store
from .prospect_models import OfferProvenance, ProspectArchive


class BenchmarkContext(str, Enum):
    """Explicitly controls whether retailer volume expectations are applicable."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    PRODUCTION = "PRODUCTION"
    GOLDEN = "GOLDEN"

    @classmethod
    def coerce(cls, value: BenchmarkContext | str) -> BenchmarkContext:
        if isinstance(value, cls):
            return value
        return cls(str(value).upper())


@dataclass(frozen=True)
class RetailerQualityPolicy:
    expected_min_offers: int
    pass_count_ratio: float = 0.80
    fail_count_ratio: float = 0.30
    min_import_rate: float = 80.0
    min_provenance_rate: float = 95.0
    min_package_rate: float = 45.0
    min_image_rate: float = 35.0


# Volume values are benchmark inputs only. They never change CollectionRun.status
# and are ignored unless a caller opts into PRODUCTION or GOLDEN evaluation.
RETAILER_QUALITY_POLICIES: dict[str, RetailerQualityPolicy] = {
    "REWE": RetailerQualityPolicy(expected_min_offers=150, min_image_rate=50.0),
    "Lidl": RetailerQualityPolicy(expected_min_offers=120, min_image_rate=35.0),
    "Netto Marken-Discount": RetailerQualityPolicy(expected_min_offers=250, min_image_rate=20.0),
    "ALDI SÜD": RetailerQualityPolicy(expected_min_offers=130, min_image_rate=20.0),
    "ALDI NORD": RetailerQualityPolicy(expected_min_offers=130, min_image_rate=20.0),
    "EDEKA": RetailerQualityPolicy(expected_min_offers=60, min_image_rate=20.0),
    "PENNY": RetailerQualityPolicy(expected_min_offers=100, min_image_rate=20.0),
}
DEFAULT_POLICY = RetailerQualityPolicy(expected_min_offers=50, min_image_rate=10.0)


class CollectionQualitySnapshot(Base):
    """Structured technical, quality and benchmark state for one run."""

    __tablename__ = "collection_quality_snapshots"
    __table_args__ = (UniqueConstraint("run_id", name="uq_collection_quality_run"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    run_status: Mapped[str] = mapped_column(String(30), index=True)
    quality_status: Mapped[str] = mapped_column(String(20), index=True)
    benchmark_status: Mapped[str] = mapped_column(String(20), index=True)
    benchmark_context: Mapped[str] = mapped_column(String(20), index=True)
    quality_score: Mapped[float] = mapped_column(Float)
    metrics_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    @property
    def qa_status(self) -> str:
        return self.quality_status


def _pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100.0, 1)


def _latest_archive(db: Session, store: Store) -> ProspectArchive | None:
    return (
        db.query(ProspectArchive)
        .filter(ProspectArchive.store_id == store.id)
        .order_by(ProspectArchive.fetched_at.desc(), ProspectArchive.id.desc())
        .first()
    )


def _offers_for_archive(db: Session, store: Store, archive: ProspectArchive | None) -> list[Offer]:
    query = db.query(Offer).filter(Offer.store_id == store.id)
    if archive is not None:
        if archive.valid_from is not None:
            query = query.filter(Offer.valid_from == archive.valid_from)
        if archive.valid_to is not None:
            query = query.filter(Offer.valid_to == archive.valid_to)
    return query.all()


def _suspicious_name(name: str) -> bool:
    text = re.sub(r"\s+", " ", (name or "").strip().lower())
    if len(text) < 4:
        return True
    if text in {"peanut", "gegart", "je st", "je st.", "schoko", "kl ii", "kl. ii", "100% pflanzlich"}:
        return True
    return bool(re.fullmatch(r"(?:feine würzung|grillfertig gewürzt|aus .+|je \d+\s*(?:g|kg|ml|l|st\.?))", text))


def evaluate_collection_quality(
    db: Session,
    *,
    store: Store,
    run: CollectionRun,
    rows: list,
    summary,
    images_saved: int,
    run_status: str = "success",
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
) -> tuple[str, str, float, dict]:
    """Evaluate data quality and optional retailer benchmarks independently."""

    context = BenchmarkContext.coerce(benchmark_context)
    policy = RETAILER_QUALITY_POLICIES.get(store.retailer, DEFAULT_POLICY)
    archive = _latest_archive(db, store)
    offers = _offers_for_archive(db, store, archive)
    offer_ids = {offer.id for offer in offers}
    product_ids = {offer.master_product_id for offer in offers}
    products = db.query(MasterProduct).filter(MasterProduct.id.in_(product_ids)).all() if product_ids else []

    package_count = sum(1 for product in products if (product.package_size or "").strip())
    suspicious_count = sum(1 for product in products if _suspicious_name(product.name))
    unit_price_count = sum(1 for offer in offers if offer.unit_price is not None and offer.unit_price > 0)
    media_rows = (
        db.query(MediaAsset)
        .filter(
            MediaAsset.kind == "product",
            MediaAsset.active.is_(True),
            MediaAsset.master_product_id.in_(product_ids),
        )
        .all()
        if product_ids
        else []
    )
    image_product_ids = {media.master_product_id for media in media_rows if media.master_product_id is not None}

    provenance_offer_ids: set[int] = set()
    if archive is not None and offer_ids:
        provenance_offer_ids = {
            provenance.offer_id
            for provenance in db.query(OfferProvenance).filter(
                OfferProvenance.prospect_archive_id == archive.id,
                OfferProvenance.offer_id.in_(offer_ids),
            )
            if 1 <= provenance.prospect_page <= archive.page_count
        }
    occurrence_rows = (
        db.query(OfferOccurrence).filter(OfferOccurrence.offer_id.in_(offer_ids)).all()
        if offer_ids
        else []
    )
    occurrence_offer_ids = {occurrence.offer_id for occurrence in occurrence_rows}

    received = len(rows)
    imported = int(summary.imported or 0)
    import_rate = _pct(imported, received)
    expected_offer_ratio = _pct(imported, policy.expected_min_offers)
    package_rate = _pct(package_count, len(products))
    unit_price_rate = _pct(unit_price_count, len(offers))
    image_rate = _pct(len(image_product_ids), len(product_ids))
    provenance_rate = _pct(len(provenance_offer_ids), len(offer_ids)) if archive else 0.0
    occurrence_rate = _pct(len(occurrence_offer_ids), len(offer_ids))
    suspicious_rate = _pct(suspicious_count, len(products))

    quality_score = 0.0
    quality_score += min(import_rate / 100.0, 1.0) * 25.0
    quality_score += min(package_rate / 100.0, 1.0) * 15.0
    quality_score += min(unit_price_rate / 100.0, 1.0) * 15.0
    quality_score += min(image_rate / 100.0, 1.0) * 15.0
    quality_score += min(provenance_rate / 100.0, 1.0) * 25.0
    quality_score += min(occurrence_rate / 100.0, 1.0) * 5.0
    quality_score -= min(suspicious_rate, 20.0)
    quality_score = round(max(0.0, min(quality_score, 100.0)), 1)

    quality_reasons: list[str] = []
    quality_fail = False
    if imported <= 0:
        quality_fail = True
        quality_reasons.append("no_imported_offers")
    if received > 0 and import_rate < 50.0:
        quality_fail = True
        quality_reasons.append("import_rate_below_50")
    elif received > 0 and import_rate < policy.min_import_rate:
        quality_reasons.append("import_rate_below_target")
    if archive is not None and provenance_rate < policy.min_provenance_rate:
        quality_reasons.append("provenance_below_target")
    if package_rate < policy.min_package_rate:
        quality_reasons.append("package_rate_low")
    if image_rate < policy.min_image_rate:
        quality_reasons.append("image_rate_low")
    if suspicious_count:
        quality_reasons.append("suspicious_product_names")

    if quality_fail:
        quality_status = "FAIL"
    elif quality_reasons or quality_score < 80.0:
        quality_status = "WARN"
    else:
        quality_status = "PASS"

    benchmark_reasons: list[str] = []
    if context is BenchmarkContext.NOT_APPLICABLE:
        benchmark_status = "NOT_APPLICABLE"
    elif imported < policy.expected_min_offers * policy.fail_count_ratio:
        benchmark_status = "FAIL"
        benchmark_reasons.append("offer_count_far_below_baseline")
    elif imported < policy.expected_min_offers * policy.pass_count_ratio:
        benchmark_status = "WARN"
        benchmark_reasons.append("offer_count_below_pass_floor")
    else:
        benchmark_status = "PASS"

    metrics = {
        "run_status": run_status,
        "quality_status": quality_status,
        "benchmark_status": benchmark_status,
        "benchmark_context": context.value,
        "quality_score": quality_score,
        "retailer": store.retailer,
        "expected_min_offers": policy.expected_min_offers,
        "offers_received": received,
        "offers_imported": imported,
        "import_rate": import_rate,
        "expected_offer_ratio": expected_offer_ratio,
        "archive_created": archive is not None,
        "archive_id": archive.id if archive else None,
        "archive_pages": archive.page_count if archive else 0,
        "provenance_links": len(provenance_offer_ids),
        "provenance_rate": provenance_rate,
        "package_rate": package_rate,
        "unit_price_rate": unit_price_rate,
        "image_rate": image_rate,
        "occurrence_rate": occurrence_rate,
        "suspicious_name_count": suspicious_count,
        "suspicious_rate": suspicious_rate,
        "quality_rejected": int(summary.rejected_quality or 0),
        "online_rejected": int(summary.rejected_online or 0),
        "store_rejected": int(summary.rejected_store or 0),
        "date_rejected": int(summary.rejected_date or 0),
        "quality_reasons": quality_reasons,
        "benchmark_reasons": benchmark_reasons,
    }
    return quality_status, benchmark_status, quality_score, metrics


def persist_collection_quality(
    db: Session,
    *,
    store: Store,
    run: CollectionRun,
    rows: list,
    summary,
    images_saved: int,
    run_status: str = "success",
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
) -> tuple[str, dict]:
    quality_status, benchmark_status, score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=summary,
        images_saved=images_saved,
        run_status=run_status,
        benchmark_context=benchmark_context,
    )
    snapshot = db.query(CollectionQualitySnapshot).filter(CollectionQualitySnapshot.run_id == run.id).first()
    payload = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    if snapshot is None:
        snapshot = CollectionQualitySnapshot(
            run_id=run.id,
            store_id=store.id,
            retailer=store.retailer,
            run_status=run_status,
            quality_status=quality_status,
            benchmark_status=benchmark_status,
            benchmark_context=metrics["benchmark_context"],
            quality_score=score,
            metrics_json=payload,
        )
        db.add(snapshot)
    else:
        snapshot.run_status = run_status
        snapshot.quality_status = quality_status
        snapshot.benchmark_status = benchmark_status
        snapshot.benchmark_context = metrics["benchmark_context"]
        snapshot.quality_score = score
        snapshot.metrics_json = payload
        snapshot.created_at = datetime.utcnow()
    db.flush()

    diagnostic = (
        f"run_status={run_status} quality_status={quality_status} "
        f"benchmark_status={benchmark_status} benchmark_context={metrics['benchmark_context']} "
        f"quality_score={score:.1f} import_rate={metrics['import_rate']:.1f} "
        f"archive_created={str(metrics['archive_created']).lower()} "
        f"provenance_rate={metrics['provenance_rate']:.1f} "
        f"package_rate={metrics['package_rate']:.1f} "
        f"unit_price_rate={metrics['unit_price_rate']:.1f} "
        f"image_rate={metrics['image_rate']:.1f} suspicious={metrics['suspicious_name_count']}"
    )
    return diagnostic, metrics
