from __future__ import annotations

from copy import deepcopy

from .edeka_fellenzer_offer_audit import FELLENZER_MARKET_ID, fetch_fellenzer_offers
from .edeka_web_offer_api_audit import _fetch_edeka_api
from .edeka_web_offer_category_audit import _fetch_all_categories
from .extractor_adapter import normalize_master_key
from .models import Store
from .web_offer_audit import WebAuditError, WebAuditResult, WebOfferRecord
from .web_offer_audit_runtime import quality_deduplicate


def _market_id(store: Store) -> str:
    return "".join(character for character in str(store.external_id or "") if character.isdigit())


def _identity_key(offer: WebOfferRecord) -> tuple[str, str] | None:
    if offer.ean:
        return ("ean", offer.ean.strip())
    if offer.external_product_id:
        return ("product", offer.external_product_id.strip())
    key = normalize_master_key(offer.name, offer.quantity_value, offer.quantity_unit)
    return ("normalized", key) if key else None


def _merge_pair(central: WebOfferRecord, local: WebOfferRecord) -> tuple[WebOfferRecord, bool]:
    merged = deepcopy(central)
    price_conflict = (
        central.price is not None
        and local.price is not None
        and abs(central.price - local.price) >= 0.005
    )

    for field_name in (
        "brand", "description", "old_price", "unit_price", "quantity",
        "quantity_value", "quantity_unit", "packaging_text", "valid_from",
        "valid_to", "category", "source_category", "image_url",
        "image_source", "image_alt", "ean",
    ):
        if getattr(merged, field_name) in (None, "") and getattr(local, field_name) not in (None, ""):
            setattr(merged, field_name, getattr(local, field_name))

    merged.provenance = {
        "sources": ["edeka_central", "edeka_local_fellenzer"],
        "central": central.provenance,
        "local": local.provenance,
        "price_conflict": price_conflict,
        "central_price": central.price,
        "local_price": local.price,
    }
    return merged.validate(), price_conflict


def merge_edeka_sources(central: WebAuditResult, local: WebAuditResult | None) -> WebAuditResult:
    central_rows, central_dupes = quality_deduplicate(list(central.offers))
    local_rows, local_dupes = quality_deduplicate(list(local.offers)) if local else ([], 0)

    central_by_identity: dict[tuple[str, str], WebOfferRecord] = {}
    merged_rows: list[WebOfferRecord] = list(central_rows)
    merged_index: dict[tuple[str, str], int] = {}
    for index, row in enumerate(merged_rows):
        key = _identity_key(row)
        if key:
            central_by_identity[key] = row
            merged_index[key] = index

    overlap = 0
    local_only = 0
    price_conflicts = 0
    for local_row in local_rows:
        key = _identity_key(local_row)
        if key is not None and key in central_by_identity:
            overlap += 1
            merged_row, conflict = _merge_pair(central_by_identity[key], local_row)
            price_conflicts += int(conflict)
            merged_rows[merged_index[key]] = merged_row
        else:
            local_only += 1
            local_row.provenance = {
                "sources": ["edeka_local_fellenzer"],
                "local": local_row.provenance,
            }
            merged_rows.append(local_row)

    merged_rows, cross_dupes = quality_deduplicate(merged_rows)
    central_count = len(central_rows)
    local_count = len(local_rows)
    source_breakdown = {
        "central_count": central_count,
        "local_count": local_count,
        "source_overlap": overlap,
        "central_only": max(central_count - overlap, 0),
        "local_only": local_only,
        "price_conflicts": price_conflicts,
        "unique_combined": len(merged_rows),
    }

    artifacts = dict(central.artifacts or {})
    artifacts.update({
        "source_breakdown": source_breakdown,
        "central_collector_path": central.collector_path,
        "local_collector_path": local.collector_path if local else None,
        "central_source_url": central.source_url,
        "local_source_url": local.source_url if local else None,
    })

    return WebAuditResult(
        offers=merged_rows,
        source_url=central.source_url,
        final_url=central.final_url,
        collector_path="edeka_central_plus_local",
        raw_count=central.raw_count + (local.raw_count if local else 0),
        duplicate_count=(
            central.duplicate_count + central_dupes
            + (local.duplicate_count if local else 0) + local_dupes + cross_dupes
        ),
        message=(
            f"EDEKA Quellen kombiniert: zentral {central_count}, lokal {local_count}, "
            f"Überschneidung {overlap}, lokal zusätzlich {local_only}, unique {len(merged_rows)}"
        ),
        artifacts=artifacts,
    )


def fetch_central_edeka(store: Store) -> WebAuditResult:
    try:
        result = _fetch_all_categories(store)
    except WebAuditError:
        result = _fetch_edeka_api(store)
    result.artifacts = dict(result.artifacts or {})
    result.artifacts["market_id"] = _market_id(store)
    result.artifacts["source_role"] = "central_primary"
    return result


def fetch_local_edeka(store: Store) -> WebAuditResult | None:
    if _market_id(store) != FELLENZER_MARKET_ID:
        return None
    try:
        result = fetch_fellenzer_offers(store)
    except WebAuditError:
        return None
    result.artifacts = dict(result.artifacts or {})
    result.artifacts["market_id"] = _market_id(store)
    result.artifacts["source_role"] = "local_supplement"
    return result


def fetch_combined_edeka(store: Store) -> WebAuditResult:
    central = fetch_central_edeka(store)
    local = fetch_local_edeka(store)
    return merge_edeka_sources(central, local)
