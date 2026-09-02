from __future__ import annotations

from copy import deepcopy

from .edeka_central_page_audit import central_market_page_url, fetch_central_market_page
from .edeka_fellenzer_offer_audit import FELLENZER_MARKET_ID, fetch_fellenzer_offers
from .edeka_marketsearch_offer_audit import fetch_resolved_market_offers
from .edeka_web_offer_api_audit import _fetch_edeka_api
from .edeka_web_offer_category_audit import _fetch_all_categories
from .extractor_adapter import normalize_master_key
from .models import Store
from .web_offer_audit import WebAuditError, WebAuditResult, WebOfferRecord
from .web_offer_audit_runtime import quality_deduplicate


def _market_id(store: Store) -> str:
    return "".join(character for character in str(store.external_id or "") if character.isdigit())


def _central_market_page(store: Store) -> str:
    return central_market_page_url(_market_id(store))


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
        "central_completeness": (central.artifacts or {}).get("central_completeness", "unknown"),
        "local_status": local.status if local else "not_applicable",
    }

    artifacts = dict(central.artifacts or {})
    artifacts.update({
        "source_breakdown": source_breakdown,
        "central_collector_path": central.collector_path,
        "local_collector_path": local.collector_path if local else None,
        "central_source_url": central.source_url,
        "central_market_page_url": central.final_url,
        "local_source_url": local.source_url if local else None,
        "local_error": (local.artifacts or {}).get("local_error") if local else None,
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
        status="partial" if central.status == "partial" or (local and local.status == "partial") else central.status,
        message=(
            f"EDEKA Quellen kombiniert: zentral {central_count}, lokal {local_count}, "
            f"Überschneidung {overlap}, lokal zusätzlich {local_only}, unique {len(merged_rows)}, "
            f"Preis-Konflikte {price_conflicts}"
        ),
        artifacts=artifacts,
    )


def fetch_central_edeka(store: Store) -> WebAuditResult:
    errors: list[str] = []
    market_page_diagnostics: dict = {}
    try:
        return fetch_central_market_page(store)
    except WebAuditError as page_exc:
        errors.append(f"central_market_page:{page_exc.error_type}")
        market_page_diagnostics.update(dict(page_exc.artifacts or {}))
        market_page_diagnostics["market_page_error_type"] = page_exc.error_type
        market_page_diagnostics["market_page_error"] = str(page_exc)[:1000]
    except Exception as page_exc:
        errors.append(f"central_market_page:{type(page_exc).__name__}")
        market_page_diagnostics.update(dict(getattr(page_exc, "diagnostics", {}) or {}))
        market_page_diagnostics["market_page_error_type"] = type(page_exc).__name__
        market_page_diagnostics["market_page_error"] = str(page_exc)[:1000]

    try:
        result = fetch_resolved_market_offers(store)
    except WebAuditError as exc:
        errors.append(f"marketsearch_resolver:{exc.error_type}")
        try:
            result = _fetch_all_categories(store)
        except WebAuditError as category_exc:
            errors.append(f"category_api:{category_exc.error_type}")
            try:
                result = _fetch_edeka_api(store)
            except WebAuditError as api_exc:
                errors.append(f"legacy_api:{api_exc.error_type}")
                result = WebAuditResult(
                    offers=[], source_url=_central_market_page(store), final_url=_central_market_page(store),
                    collector_path="edeka_central_unavailable", raw_count=0, status="partial",
                    message="EDEKA-Zentralquelle nicht vollständig abrufbar.", artifacts={},
                )

    result.artifacts = dict(result.artifacts or {})
    result.artifacts["market_page_id"] = _market_id(store)
    result.artifacts["source_role"] = "central_primary"
    result.artifacts["collector_endpoint_url"] = result.final_url
    if errors:
        result.artifacts["central_fallbacks"] = errors
    attempts = list(market_page_diagnostics.get("fetch_attempts") or [])
    status_attempt = next(
        (attempt for attempt in attempts if attempt.get("http_status") is not None),
        attempts[-1] if attempts else {},
    )
    explicit_block_reason = next(
        (
            attempt.get("body_marker")
            for attempt in attempts
            if attempt.get("body_marker") not in (None, "")
        ),
        None,
    )
    structured_endpoint = next(
        (
            result.artifacts.get(key)
            for key in ("api_url", "request_url", "endpoint_url", "collector_endpoint_url")
            if result.artifacts.get(key)
        ),
        None,
    )
    result.final_url = _central_market_page(store)
    result.status = "partial"
    result.artifacts.update({
        "central_completeness": "partial",
        "central_completeness_status": "partial",
        "central_completeness_reason": "Offizielle Marktseite fehlgeschlagen; API-Daten sind nur unvollständige Diagnose-Evidenz.",
        "known_reference_count": 224 if _market_id(store) == "071378" else None,
        "known_reference_visible_count": 224 if _market_id(store) == "071378" else None,
        "central_expected_reference_count": 224 if _market_id(store) == "071378" else None,
        "central_categories_detected": 0,
        "central_categories_completed": 0,
        "central_raw_count": result.raw_count,
        "central_unique_count": len(result.offers),
        "parsed_central_count": len(result.offers),
        "central_fetch_method": f"MARKET_PAGE_FAILED -> {result.collector_path}",
        "central_fetch_http_status": status_attempt.get("http_status"),
        "central_fetch_http_version": status_attempt.get("http_version"),
        "central_fetch_final_host": status_attempt.get("final_host") or "www.edeka.de",
        "central_fetch_response_headers": status_attempt.get("response_headers", {}),
        "central_fetch_redirect_chain": status_attempt.get("redirect_chain", []),
        "central_fetch_block_reason": (
            explicit_block_reason
            or market_page_diagnostics.get("block_reason")
            or market_page_diagnostics.get("market_page_error_type")
        ),
        "central_fetch_fallback_used": True,
        "central_structured_endpoint": structured_endpoint,
        "central_dom_count": 0,
        "central_parsed_count": len(result.offers),
        "central_reference_count": 224 if _market_id(store) == "071378" else None,
        "central_fetch_attempts": attempts,
    })
    return result


def fetch_local_edeka(store: Store) -> WebAuditResult | None:
    if _market_id(store) != FELLENZER_MARKET_ID:
        return None
    try:
        result = fetch_fellenzer_offers(store)
    except WebAuditError as exc:
        return WebAuditResult(
            offers=[], source_url="https://edeka-fellenzer.de/angebote/",
            final_url="https://edeka-fellenzer.de/angebote/",
            collector_path="edeka_local_fellenzer_unavailable", raw_count=0, status="partial",
            message=f"Lokale Fellenzer-Quelle nicht verfügbar: {exc.error_type}",
            artifacts={"local_error": exc.error_type, "local_error_message": str(exc)},
        )
    result.artifacts = dict(result.artifacts or {})
    result.artifacts["market_id"] = _market_id(store)
    result.artifacts["source_role"] = "local_supplement"
    return result


def fetch_combined_edeka(store: Store) -> WebAuditResult:
    central = fetch_central_edeka(store)
    local = fetch_local_edeka(store)
    return merge_edeka_sources(central, local)
