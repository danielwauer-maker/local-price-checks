from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy.orm import Session

from .admin_learning import resolve_product_alias
from .engine_v140.offer_quality import evaluate_offer
from .engine_v140.product_cleaning import clean_product_name
from .extractor_adapter import assess_collected_offer, normalize_master_key
from .models import MasterProduct, Offer, Store
from .physical_market_identity import canonical_store_map


def _date(value: str | None):
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _physical_store_ids(db: Session, store: Store) -> list[int]:
    rows = db.query(Store).filter(Store.retailer == store.retailer).all()
    mapping = canonical_store_map(rows)
    canonical = mapping.get(store.id, store)
    return [row.id for row in rows if mapping.get(row.id, row).id == canonical.id]


def _compact(value: object, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _quality_rejection_examples(rows: list, limit: int = 3) -> list[str]:
    """Return concrete, read-only diagnostics for rows rejected by offer QA."""
    examples: list[str] = []
    for row in rows:
        assessment = assess_collected_offer(row)
        if assessment.rejection != "quality":
            continue

        quality = evaluate_offer(row)
        if quality.accepted:
            reasons = ("Komplexe Promotion nicht eindeutig auflösbar",)
        else:
            reasons = quality.reasons or ("Qualitätsprüfung abgelehnt",)

        quantity = getattr(row, "quantity", None)
        unit = getattr(row, "unit", None) or ""
        package = f"{quantity:g} {unit}" if isinstance(quantity, (int, float)) else str(unit or "-")
        examples.append(
            "quality_reject["
            f"name={_compact(getattr(row, 'product_name', ''), 90)}; "
            f"price={getattr(row, 'price', None)}; "
            f"pack={_compact(package, 45)}; "
            f"reason={_compact(' / '.join(reasons), 180)}; "
            f"raw={_compact(getattr(row, 'source_text', ''), 260)}"
            "]"
        )
        if len(examples) >= limit:
            break
    return examples


def _record_skipped_reconcile_diagnostic(run, summary, rows: list) -> None:
    rejected = (
        int(summary.rejected_online)
        + int(summary.rejected_quality)
        + int(summary.rejected_store)
        + int(summary.rejected_date)
    )
    diagnostic = (
        "authoritative_reconcile=SKIPPED_REJECTIONS "
        f"imported={summary.imported}/{len(rows)} "
        f"rejected_online={summary.rejected_online} "
        f"rejected_quality={summary.rejected_quality} "
        f"rejected_store={summary.rejected_store} "
        f"rejected_date={summary.rejected_date}"
    )
    if summary.rejected_quality:
        examples = _quality_rejection_examples(rows)
        if examples:
            diagnostic += " | " + " | ".join(examples)
    # Put the diagnostic first so the concrete rejected row survives the
    # CollectionRun.message size cap even when the collector message is long.
    run.message = " | ".join(part for part in (diagnostic, run.message or "") if part)[:1800]


def reconcile_rewe_authoritative_snapshot(db: Session, store: Store, rows: list) -> int | None:
    """Deactivate stale current REWE offers after one complete authoritative snapshot.

    ``None`` means reconciliation could not be proven safe and was therefore
    aborted.  No offer, occurrence or provenance row is deleted.  Offers absent
    from a proven fresh snapshot are only marked ``local_store_offer=False``;
    the normal importer reactivates them if they appear again later.
    """
    if store.retailer != "REWE" or not rows:
        return None

    store_ids = _physical_store_ids(db, store)
    active_offer_ids: set[int] = set()
    periods: set[tuple] = set()

    for row in rows:
        valid_from = _date(getattr(row, "valid_from", None))
        valid_to = _date(getattr(row, "valid_to", None))
        price = getattr(row, "price", None)
        name = clean_product_name(getattr(row, "product_name", "") or "")
        if not valid_from or not valid_to or valid_to < valid_from or price is None or not name:
            return None

        periods.add((valid_from, valid_to))
        key = normalize_master_key(name, getattr(row, "quantity", None), getattr(row, "unit", None))
        product = resolve_product_alias(db, key)
        if not product:
            product = db.query(MasterProduct).filter(MasterProduct.normalized_key == key).first()
        if not product:
            return None

        matches = (
            db.query(Offer)
            .filter(
                Offer.store_id.in_(store_ids),
                Offer.master_product_id == product.id,
                Offer.valid_from == valid_from,
                Offer.valid_to == valid_to,
                Offer.price == float(price),
            )
            .all()
        )
        if not matches:
            return None
        active_offer_ids.update(offer.id for offer in matches)

    if not active_offer_ids or not periods:
        return None

    stale: list[Offer] = []
    for valid_from, valid_to in periods:
        stale.extend(
            db.query(Offer)
            .filter(
                Offer.store_id.in_(store_ids),
                Offer.valid_from == valid_from,
                Offer.valid_to == valid_to,
                Offer.local_store_offer.is_(True),
                ~Offer.id.in_(active_offer_ids),
            )
            .all()
        )

    unique = {offer.id: offer for offer in stale}
    for offer in unique.values():
        offer.local_store_offer = False
    if unique:
        db.commit()
    return len(unique)


def reconcile_completed_rewe_collection(db: Session, store: Store, result: dict, summary, run) -> int | None:
    """Reconcile only a fully admitted, technically successful REWE collection.

    Any rejection, warning, empty/partial source, or unresolved identity leaves
    production untouched. Rejections are persisted diagnostically on the run so
    an operator can see the exact rejected row and QA reason without weakening
    the fail-closed gate. A reconciliation safety failure downgrades the run to
    warning so it cannot silently masquerade as an authoritative success.
    """
    if store.retailer != "REWE" or run.status != "success":
        return None
    rows = list(result.get("offers") or [])
    rejected = (
        int(summary.rejected_online)
        + int(summary.rejected_quality)
        + int(summary.rejected_store)
        + int(summary.rejected_date)
    )
    if not rows:
        return None
    if summary.imported != len(rows) or rejected:
        _record_skipped_reconcile_diagnostic(run, summary, rows)
        db.commit()
        return None

    reconciled = reconcile_rewe_authoritative_snapshot(db, store, rows)
    if reconciled is None:
        run.status = "warning"
        run.message = " | ".join(
            part for part in (run.message or "", "authoritative_reconcile=ABORTED_FAIL_CLOSED") if part
        )[:1800]
        db.commit()
        return None

    run.message = " | ".join(
        part for part in (run.message or "", f"authoritative_reconciled_inactive={reconciled}") if part
    )[:1800]
    db.commit()
    return reconciled
