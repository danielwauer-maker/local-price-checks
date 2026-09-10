from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from .models import MasterProduct, Offer, ProductBarcode
from .web_offer_audit import _fold, _quantity, normalize_master_key
from .web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun
from .web_offer_audit_runtime import period_bounds


BETA_COMPLETENESS_THRESHOLD = 95.0
BETA_PRICE_ACCURACY_THRESHOLD = 99.0
BETA_VALIDITY_ACCURACY_THRESHOLD = 99.0


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator * 100.0 / denominator, 1)


def _product_keys(product: MasterProduct) -> tuple[str, str]:
    display = " ".join(filter(None, (product.brand, product.name)))
    _, quantity_value, quantity_unit = _quantity(product.package_size)
    return (
        normalize_master_key(display, quantity_value, quantity_unit),
        normalize_master_key(display),
    )


def _source_keys(row: WebOfferAuditItem) -> tuple[str, str]:
    display = " ".join(filter(None, (row.brand, row.name)))
    return (
        normalize_master_key(display, row.quantity_value, row.quantity_unit),
        normalize_master_key(display),
    )


def build_offer_accuracy_scorecard(db: Session, run: WebOfferAuditRun) -> dict[str, Any]:
    """Compare isolated retailer evidence with persisted production offers.

    This is deliberately read-only.  It never imports, deletes, rewrites or
    merges offers/products.  The scorecard is intended to make beta readiness
    measurable while keeping ambiguous identity cases visible for review.
    """
    period_start, period_end = period_bounds(run.period_key)
    source_rows = [row for row in run.offers if row.valid]
    production_rows = (
        db.query(Offer, MasterProduct)
        .join(MasterProduct, MasterProduct.id == Offer.master_product_id)
        .filter(
            Offer.store_id == run.store_id,
            Offer.valid_from <= period_end,
            Offer.valid_to >= period_start,
        )
        .order_by(Offer.id)
        .all()
    )

    barcode_map: dict[int, set[str]] = {}
    product_ids = {product.id for _, product in production_rows}
    if product_ids:
        for product_id, barcode in (
            db.query(ProductBarcode.master_product_id, ProductBarcode.barcode)
            .filter(ProductBarcode.master_product_id.in_(product_ids))
            .all()
        ):
            barcode_map.setdefault(product_id, set()).add(barcode)

    source_context_mismatch = sum(
        1
        for row in source_rows
        if row.store_id != run.store_id or _fold(row.retailer) != _fold(run.retailer)
    )
    eligible_source = [
        row
        for row in source_rows
        if row.store_id == run.store_id and _fold(row.retailer) == _fold(run.retailer)
    ]

    used_source_ids: set[int] = set()
    matched = 0
    exact_matches = 0
    price_match = 0
    price_mismatch = 0
    validity_match = 0
    validity_mismatch = 0
    validity_unverifiable = 0
    ambiguous_identity = 0

    def available() -> list[WebOfferAuditItem]:
        return [row for row in eligible_source if row.id not in used_source_ids]

    for offer, product in production_rows:
        rows = available()
        exact_key, family_key = _product_keys(product)
        match: WebOfferAuditItem | None = None

        barcodes = barcode_map.get(product.id, set())
        if barcodes:
            barcode_matches = [row for row in rows if row.ean and row.ean in barcodes]
            if len(barcode_matches) == 1:
                match = barcode_matches[0]
            elif len(barcode_matches) > 1:
                same_price = [row for row in barcode_matches if row.price is not None and abs(row.price - offer.price) < 0.005]
                if len(same_price) == 1:
                    match = same_price[0]
                else:
                    ambiguous_identity += 1
                    continue

        if match is None:
            exact_candidates = [row for row in rows if _source_keys(row)[0] == exact_key]
            if len(exact_candidates) == 1:
                match = exact_candidates[0]
            elif len(exact_candidates) > 1:
                same_price = [row for row in exact_candidates if row.price is not None and abs(row.price - offer.price) < 0.005]
                if len(same_price) == 1:
                    match = same_price[0]
                else:
                    ambiguous_identity += 1
                    continue

        if match is None:
            family_candidates = [row for row in rows if _source_keys(row)[1] == family_key]
            if len(family_candidates) == 1:
                match = family_candidates[0]
            elif len(family_candidates) > 1:
                ambiguous_identity += 1
                continue

        if match is None:
            continue

        used_source_ids.add(match.id)
        matched += 1
        price_ok = match.price is not None and abs(match.price - offer.price) < 0.005
        if price_ok:
            price_match += 1
        else:
            price_mismatch += 1

        if match.valid_from is None or match.valid_to is None:
            validity_unverifiable += 1
            validity_ok = False
        else:
            validity_ok = match.valid_from == offer.valid_from and match.valid_to == offer.valid_to
            if validity_ok:
                validity_match += 1
            else:
                validity_mismatch += 1

        if price_ok and validity_ok:
            exact_matches += 1

    source_count = len(eligible_source)
    production_count = len(production_rows)
    source_only = max(source_count - matched, 0)
    production_only = max(production_count - matched, 0)
    completeness_pct = _pct(matched, source_count)
    price_accuracy_pct = _pct(price_match, matched)
    validity_verifiable = validity_match + validity_mismatch
    validity_accuracy_pct = _pct(validity_match, validity_verifiable)
    exact_accuracy_pct = _pct(exact_matches, source_count)

    product_key_counts = Counter(_product_keys(product)[0] for _, product in production_rows)
    production_duplicate_products = sum(count - 1 for count in product_key_counts.values() if count > 1)

    beta_ready = bool(
        source_count > 0
        and completeness_pct is not None
        and completeness_pct >= BETA_COMPLETENESS_THRESHOLD
        and price_accuracy_pct is not None
        and price_accuracy_pct >= BETA_PRICE_ACCURACY_THRESHOLD
        and validity_accuracy_pct is not None
        and validity_accuracy_pct >= BETA_VALIDITY_ACCURACY_THRESHOLD
        and validity_unverifiable == 0
        and source_context_mismatch == 0
        and production_duplicate_products == 0
        and ambiguous_identity == 0
    )

    return {
        "accuracy_source_count": source_count,
        "accuracy_production_count": production_count,
        "accuracy_matched": matched,
        "accuracy_source_only": source_only,
        "accuracy_production_only": production_only,
        "accuracy_price_match": price_match,
        "accuracy_price_mismatch": price_mismatch,
        "accuracy_validity_match": validity_match,
        "accuracy_validity_mismatch": validity_mismatch,
        "accuracy_validity_unverifiable": validity_unverifiable,
        "accuracy_market_context_mismatch": source_context_mismatch,
        "accuracy_ambiguous_identity": ambiguous_identity,
        "accuracy_production_duplicate_products": production_duplicate_products,
        "accuracy_completeness_pct": completeness_pct,
        "accuracy_price_accuracy_pct": price_accuracy_pct,
        "accuracy_validity_accuracy_pct": validity_accuracy_pct,
        "accuracy_exact_pct": exact_accuracy_pct,
        "accuracy_beta_ready": beta_ready,
    }
