from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from .models import MasterProduct, Offer, ProductBarcode, Store
from .physical_market_identity import canonical_store_map
from .prospect_models import OfferProvenance
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


def _physical_store_ids(db: Session, run: WebOfferAuditRun) -> tuple[int, ...]:
    """Resolve legacy/duplicate Store rows to one physical-market comparison scope."""
    rows = db.query(Store).filter(Store.retailer == run.retailer).all()
    if not rows:
        return (run.store_id,)
    mapping = canonical_store_map(rows)
    run_store = next((row for row in rows if row.id == run.store_id), None)
    if run_store is None:
        return (run.store_id,)
    canonical = mapping.get(run.store_id, run_store)
    related = tuple(row.id for row in rows if mapping.get(row.id, row).id == canonical.id)
    return related or (run.store_id,)


def _source_example(row: WebOfferAuditItem) -> str:
    package = row.packaging_text or row.quantity or "ohne Packung"
    return f"source#{row.id} {row.name} · {row.price:.2f} € · {package}" if row.price is not None else f"source#{row.id} {row.name} · {package}"


def _production_example(offer: Offer, product: MasterProduct) -> str:
    package = product.package_size or "ohne Packung"
    return f"offer#{offer.id}/product#{product.id} {product.name} · {offer.price:.2f} € · {package}"


def _provenance_example(row: OfferProvenance) -> str:
    source_text = " ".join((row.source_text or "").split())
    if len(source_text) > 220:
        source_text = source_text[:217] + "..."
    details = f"prov#{row.id}/archive#{row.prospect_archive_id}/page#{row.prospect_page}"
    return f"{details} {source_text}" if source_text else details


def build_offer_accuracy_scorecard(db: Session, run: WebOfferAuditRun) -> dict[str, Any]:
    """Compare isolated retailer evidence with persisted production offers.

    This is deliberately read-only. It never imports, deletes, rewrites or
    merges offers/products. Production rows are evaluated across every Store
    alias that represents the audited physical market, so legacy duplicate
    Store ids cannot create false source-only findings.

    Completeness is deliberately bidirectional: matching every row from a
    truncated retailer audit is not enough when production contains many more
    offers. This prevents a small/incomplete audit surface from reporting a
    misleading 100% beta-readiness completeness score.
    """
    period_start, period_end = period_bounds(run.period_key)
    source_rows = [row for row in run.offers if row.valid]
    physical_store_ids = _physical_store_ids(db, run)
    production_rows = (
        db.query(Offer, MasterProduct)
        .join(MasterProduct, MasterProduct.id == Offer.master_product_id)
        .filter(
            Offer.store_id.in_(physical_store_ids),
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
    used_production_offer_ids: set[int] = set()
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
        used_production_offer_ids.add(offer.id)
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
    source_only_rows = [row for row in eligible_source if row.id not in used_source_ids]
    production_only_rows = [(offer, product) for offer, product in production_rows if offer.id not in used_production_offer_ids]
    source_only = len(source_only_rows)
    production_only = len(production_only_rows)
    comparison_count = max(source_count, production_count)
    completeness_pct = _pct(matched, comparison_count)
    source_capture_pct = _pct(matched, source_count)
    production_capture_pct = _pct(matched, production_count)
    price_accuracy_pct = _pct(price_match, matched)
    validity_verifiable = validity_match + validity_mismatch
    validity_accuracy_pct = _pct(validity_match, validity_verifiable)
    exact_accuracy_pct = _pct(exact_matches, comparison_count)

    products_by_key: dict[str, list[tuple[Offer, MasterProduct]]] = {}
    for offer, product in production_rows:
        products_by_key.setdefault(_product_keys(product)[0], []).append((offer, product))
    production_duplicate_products = sum(len(rows) - 1 for rows in products_by_key.values() if len(rows) > 1)
    duplicate_examples = [
        " / ".join(_production_example(offer, product) for offer, product in rows[:3])
        for rows in products_by_key.values()
        if len(rows) > 1
    ]

    diagnostic_offer_ids = {offer.id for offer, _ in production_only_rows}
    for rows in products_by_key.values():
        if len(rows) > 1:
            diagnostic_offer_ids.update(offer.id for offer, _ in rows)
    provenance_by_offer: dict[int, list[OfferProvenance]] = {}
    if diagnostic_offer_ids:
        for provenance in (
            db.query(OfferProvenance)
            .filter(OfferProvenance.offer_id.in_(diagnostic_offer_ids))
            .order_by(OfferProvenance.offer_id, OfferProvenance.id)
            .all()
        ):
            provenance_by_offer.setdefault(provenance.offer_id, []).append(provenance)

    production_only_provenance = []
    for offer, product in production_only_rows:
        rows = provenance_by_offer.get(offer.id, [])
        if rows:
            production_only_provenance.append(
                f"{_production_example(offer, product)} => " + " ; ".join(_provenance_example(row) for row in rows[:2])
            )
        else:
            production_only_provenance.append(f"{_production_example(offer, product)} => ohne Prospekt-Provenienz")

    duplicate_provenance = []
    for rows in products_by_key.values():
        if len(rows) <= 1:
            continue
        parts = []
        for offer, product in rows[:3]:
            provenance_rows = provenance_by_offer.get(offer.id, [])
            prov = " ; ".join(_provenance_example(row) for row in provenance_rows[:2]) or "ohne Prospekt-Provenienz"
            parts.append(f"{_production_example(offer, product)} => {prov}")
        duplicate_provenance.append(" / ".join(parts))

    beta_ready = bool(
        source_count > 0
        and completeness_pct is not None
        and completeness_pct >= BETA_COMPLETENESS_THRESHOLD
        and production_only == 0
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
        "accuracy_source_only_examples": " | ".join(_source_example(row) for row in source_only_rows[:10]) or "–",
        "accuracy_production_only_examples": " | ".join(_production_example(offer, product) for offer, product in production_only_rows[:10]) or "–",
        "accuracy_production_only_provenance": " | ".join(production_only_provenance[:10]) or "–",
        "accuracy_price_match": price_match,
        "accuracy_price_mismatch": price_mismatch,
        "accuracy_validity_match": validity_match,
        "accuracy_validity_mismatch": validity_mismatch,
        "accuracy_validity_unverifiable": validity_unverifiable,
        "accuracy_market_context_mismatch": source_context_mismatch,
        "accuracy_ambiguous_identity": ambiguous_identity,
        "accuracy_production_duplicate_products": production_duplicate_products,
        "accuracy_production_duplicate_examples": " | ".join(duplicate_examples[:10]) or "–",
        "accuracy_production_duplicate_provenance": " | ".join(duplicate_provenance[:10]) or "–",
        "accuracy_completeness_pct": completeness_pct,
        "accuracy_source_capture_pct": source_capture_pct,
        "accuracy_production_capture_pct": production_capture_pct,
        "accuracy_price_accuracy_pct": price_accuracy_pct,
        "accuracy_validity_accuracy_pct": validity_accuracy_pct,
        "accuracy_exact_pct": exact_accuracy_pct,
        "accuracy_beta_ready": beta_ready,
    }
