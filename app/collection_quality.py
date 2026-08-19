from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base
from .models import CollectionRun, MasterProduct, MediaAsset, Offer, OfferOccurrence, Store
from .prospect_models import OfferProvenance, ProspectArchive


@dataclass(frozen=True)
class RetailerQualityPolicy:
    expected_min_offers: int
    pass_count_ratio: float = 0.80
    fail_count_ratio: float = 0.30
    min_import_rate: float = 80.0
    min_provenance_rate: float = 95.0
    min_package_rate: float = 45.0
    min_image_rate: float = 35.0
    require_archive: bool = True


# Conservative first production baselines. They are deliberately below the
# known golden counts so normal week-to-week assortment changes do not create
# false FAILs. Golden fixtures can tighten these per retailer later.
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
    """Immutable-ish QA result for one concrete collection run.

    A unique row per run makes QA observable without parsing the free-text
    CollectionRun.message. Re-evaluating the same run updates the same row.
    """

    __tablename__ = "collection_quality_snapshots"
    __table_args__ = (UniqueConstraint("run_id", name="uq_collection_quality_run"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    qa_status: Mapped[str] = mapped_column(String(10), index=True)
    qa_score: Mapped[float] = mapped_column(Float)
    metrics_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


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
    if text in {"gegart", "je st", "je st.", "schoko", "kl ii", "kl. ii", "100% pflanzlich"}:
        return True
    if re.fullmatch(r"(?:feine würzung|grillfertig gewürzt|aus .+|je \d+\s*(?:g|kg|ml|l|st\.?))", text):
        return True
    return False


def evaluate_collection_quality(
    db: Session,
    *,
    store: Store,
    run: CollectionRun,
    rows: list,
    summary,
    images_saved: int,
) -> tuple[str, float, dict]:
    """Evaluate one run with retailer-independent metrics and conservative gates."""

    policy = RETAILER_QUALITY_POLICIES.get(store.retailer, DEFAULT_POLICY)
    archive = _latest_archive(db, store)
    offers = _offers_for_archive(db, store, archive)
    offer_ids = {offer.id for offer in offers}
    product_ids = {offer.master_product_id for offer in offers}

    products = (
        db.query(MasterProduct).filter(MasterProduct.id.in_(product_ids)).all()
        if product_ids else []
    )
    product_by_id = {product.id: product for product in products}
    package_count = sum(1 for product in products if (product.package_size or "").strip())
    suspicious_count = sum(1 for product in products if _suspicious_name(product.name))
    unit_price_count = sum(1 for offer in offers if offer.unit_price is not None and offer.unit_price > 0)

    image_product_ids = set()
    if product_ids:
        image_product_ids = {
            row.master_product_id
            for row in db.query(MediaAsset).filter(
                MediaAsset.kind == "product",
                MediaAsset.active.is_(True),
                MediaAsset.master_product_id.in_(product_ids),
            ).all()
            if row.master_product_id is not None
        }

    provenance_offer_ids = set()
    if archive is not None and offer_ids:
        provenance_offer_ids = {
            row.offer_id
            for row in db.query(OfferProvenance).filter(
                OfferProvenance.prospect_archive_id == archive.id,
                OfferProvenance.offer_id.in_(offer_ids),
            ).all()
            if 1 <= row.prospect_page <= archive.page_count
        }

    occurrence_offer_ids = set()
    if offer_ids:
        occurrence_offer_ids = {
            row.offer_id
            for row in db.query(OfferOccurrence).filter(OfferOccurrence.offer_id.in_(offer_ids)).all()
        }

    received = len(rows)
    imported = int(summary.imported or 0)
    import_rate = _pct(imported, received)
    count_ratio = _pct(imported, policy.expected_min_offers)
    package_rate = _pct(package_count, len(products))
    unit_price_rate = _pct(unit_price_count, len(offers))
    image_rate = _pct(len(image_product_ids), len(product_ids))
    provenance_rate = _pct(len(provenance_offer_ids), len(offer_ids)) if archive else 0.0
    occurrence_rate = _pct(len(occurrence_offer_ids), len(offer_ids))
    suspicious_rate = _pct(suspicious_count, len(products))

    # 100 point score: completeness is dominant; metadata quality contributes
    # enough to create WARNs without turning a valid offer week into a hard FAIL.
    score = 0.0
    score += min(count_ratio / 100.0, 1.0) * 30.0
    score += min(import_rate / 100.0, 1.0) * 20.0
    score += min(package_rate / 100.0, 1.0) * 10.0
    score += min(unit_price_rate / 100.0, 1.0) * 10.0
    score += min(image_rate / 100.0, 1.0) * 10.0
    score += min(provenance_rate / 100.0, 1.0) * 15.0
    score += min(occurrence_rate / 100.0, 1.0) * 5.0
    score -= min(suspicious_rate, 20.0)
    score = round(max(0.0, min(score, 100.0)), 1)

    reasons: list[str] = []
    hard_fail = False
    if imported <= 0:
        hard_fail = True
        reasons.append("no_imported_offers")
    if imported < policy.expected_min_offers * policy.fail_count_ratio:
        hard_fail = True
        reasons.append("offer_count_far_below_baseline")
    if received > 0 and import_rate < 50.0:
        hard_fail = True
        reasons.append("import_rate_below_50")

    if policy.require_archive and archive is None:
        reasons.append("archive_missing")
    if archive is not None and provenance_rate < policy.min_provenance_rate:
        reasons.append("provenance_below_target")
    if imported < policy.expected_min_offers * policy.pass_count_ratio:
        reasons.append("offer_count_below_pass_floor")
    if received > 0 and import_rate < policy.min_import_rate:
        reasons.append("import_rate_below_target")
    if package_rate < policy.min_package_rate:
        reasons.append("package_rate_low")
    if image_rate < policy.min_image_rate:
        reasons.append("image_rate_low")
    if suspicious_count:
        reasons.append("suspicious_product_names")

    if hard_fail:
        qa_status = "FAIL"
    elif reasons or score < 85.0:
        qa_status = "WARN"
    else:
        qa_status = "PASS"

    metrics = {
        "qa_status": qa_status,
        "qa_score": score,
        "retailer": store.retailer,
        "expected_min_offers": policy.expected_min_offers,
        "offers_received": received,
        "offers_imported": imported,
        "import_rate": import_rate,
        "offer_count_ratio": count_ratio,
        "archive_created": archive is not None,
        "archive_id": archive.id if archive else None,
        "archive_pages": archive.page_count if archive else 0,
        "provenance_rate": provenance_rate,
        "package_rate": package_rate,
        "unit_price_rate": unit_price_rate,
        "image_rate": image_rate,
        "occurrence_rate": occurrence_rate,
        "suspicious_names": suspicious_count,
        "suspicious_rate": suspicious_rate,
        "rejected_online": int(summary.rejected_online or 0),
        "rejected_quality": int(summary.rejected_quality or 0),
        "reasons": reasons,
    }
    return qa_status, score, metrics


def persist_collection_quality(
    db: Session,
    *,
    store: Store,
    run: CollectionRun,
    rows: list,
    summary,
    images_saved: int,
) -> tuple[str, dict]:
    qa_status, score, metrics = evaluate_collection_quality(
        db,
        store=store,
        run=run,
        rows=rows,
        summary=summary,
        images_saved=images_saved,
    )
    snapshot = db.query(CollectionQualitySnapshot).filter(CollectionQualitySnapshot.run_id == run.id).first()
    payload = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    if snapshot is None:
        snapshot = CollectionQualitySnapshot(
            run_id=run.id,
            store_id=store.id,
            retailer=store.retailer,
            qa_status=qa_status,
            qa_score=score,
            metrics_json=payload,
        )
        db.add(snapshot)
    else:
        snapshot.qa_status = qa_status
        snapshot.qa_score = score
        snapshot.metrics_json = payload
        snapshot.created_at = datetime.utcnow()
    db.flush()

    diagnostic = (
        f"qa_status={qa_status} qa_score={score:.1f} "
        f"import_rate={metrics['import_rate']:.1f} "
        f"archive_created={str(metrics['archive_created']).lower()} "
        f"provenance_rate={metrics['provenance_rate']:.1f} "
        f"package_rate={metrics['package_rate']:.1f} "
        f"unit_price_rate={metrics['unit_price_rate']:.1f} "
        f"image_rate={metrics['image_rate']:.1f} "
        f"suspicious={metrics['suspicious_names']}"
    )
    return diagnostic, metrics
