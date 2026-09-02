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


def _strong_identity_keys(offer: WebOfferRecord) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    if offer.ean and offer.ean.strip():
        keys.append(("ean", offer.ean.strip()))
    if offer.external_product_id and offer.external_product_id.strip():
        keys.append(("product", offer.external_product_id.strip()))
    return keys


def _weak_identity_key(offer: WebOfferRecord) -> str | None:
    key = normalize_master_key(offer.name, offer.quantity_value, offer.quantity_unit)
    return key or None


def _prices_match(left: WebOfferRecord, right: WebOfferRecord) -> bool:
    if left.price is None or right.price is None:
        return False
    return abs(left.price - right.price) < 0.005


def _candidate_diagnostic(
    central: WebOfferRecord,
    local: WebOfferRecord,
    *,
    decision: str,
    reason: str,
    identity_strength: str,
) -> dict:
    return {
        "decision": decision,
        "reason": reason,
        "identity_strength": identity_strength,
        "central_offer_id": central.external_offer_id,
        "local_offer_id": local.external_offer_id,
        "central_product_id": central.external_product_id,
        "local_product_id": local.external_product_id,
        "central_ean": central.ean,
        "local_ean": local.ean,
        "central_name": central.name,
        "local_name": local.name,
        "central_price": central.price,
        "local_price": local.price,
        "central_quantity": central.packaging_text or central.quantity,
        "local_quantity": local.packaging_text or local.quantity,
        "central_image_url": central.image_url,
        "local_image_url": local.image_url,
    }


def _merge_pair(
    central: WebOfferRecord,
    local: WebOfferRecord,
    *,
    match_reason: str,
    identity_strength: str,
) -> tuple[WebOfferRecord, bool]:
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
        "dedupe_decision": {
            "decision": "merged",
            "reason": match_reason,
            "identity_strength": identity_strength,
        },
        "price_conflict": price_conflict,
        "central_price": central.price,
        "local_price": local.price,
    }
    return merged.validate(), price_conflict


def merge_edeka_sources(central: WebAuditResult, local: WebAuditResult | None) -> WebAuditResult:
    central_rows, central_dupes = quality_deduplicate(list(central.offers))
    local_rows, local_dupes = quality_deduplicate(list(local.offers)) if local else ([], 0)

    merged_rows: list[WebOfferRecord] = list(central_rows)
    central_by_strong: dict[tuple[str, str], list[int]] = {}
    central_by_weak: dict[str, list[int]] = {}
    for index, row in enumerate(central_rows):
        for key in _strong_identity_keys(row):
            central_by_strong.setdefault(key, []).append(index)
        weak_key = _weak_identity_key(row)
        if weak_key:
            central_by_weak.setdefault(weak_key, []).append(index)

    overlap = 0
    local_only = 0
    price_conflicts = 0
    weak_price_mismatches = 0
    ambiguous_candidates = 0
    dedupe_candidates: list[dict] = []

    for local_row in local_rows:
        strong_indexes: set[int] = set()
        strong_reason: str | None = None
        for key in _strong_identity_keys(local_row):
            matches = central_by_strong.get(key, [])
            if matches:
                strong_indexes.update(matches)
                strong_reason = f"same_{key[0]}"

        if len(strong_indexes) == 1:
            index = next(iter(strong_indexes))
            central_row = central_rows[index]
            merged_row, conflict = _merge_pair(
                central_row,
                local_row,
                match_reason=strong_reason or "strong_identity",
                identity_strength="strong",
            )
            overlap += 1
            price_conflicts += int(conflict)
            merged_rows[index] = merged_row
            if conflict:
                dedupe_candidates.append(_candidate_diagnostic(
                    central_row,
                    local_row,
                    decision="merged_with_price_conflict",
                    reason="strong_identity_price_conflict",
                    identity_strength="strong",
                ))
            continue

        if len(strong_indexes) > 1:
            ambiguous_candidates += 1
            for index in sorted(strong_indexes)[:5]:
                dedupe_candidates.append(_candidate_diagnostic(
                    central_rows[index],
                    local_row,
                    decision="kept_separate",
                    reason="ambiguous_strong_identity_multiple_central_rows",
                    identity_strength="strong",
                ))
        else:
            weak_key = _weak_identity_key(local_row)
            weak_indexes = central_by_weak.get(weak_key, []) if weak_key else []
            same_price_indexes = [index for index in weak_indexes if _prices_match(central_rows[index], local_row)]

            if len(same_price_indexes) == 1:
                index = same_price_indexes[0]
                central_row = central_rows[index]
                merged_row, conflict = _merge_pair(
                    central_row,
                    local_row,
                    match_reason="same_normalized_name_quantity_and_price",
                    identity_strength="weak_confirmed_by_price",
                )
                overlap += 1
                price_conflicts += int(conflict)
                merged_rows[index] = merged_row
                continue

            if len(same_price_indexes) > 1:
                ambiguous_candidates += 1
                for index in same_price_indexes[:5]:
                    dedupe_candidates.append(_candidate_diagnostic(
                        central_rows[index],
                        local_row,
                        decision="kept_separate",
                        reason="ambiguous_weak_identity_multiple_same_price_rows",
                        identity_strength="weak",
                    ))
            elif weak_indexes:
                weak_price_mismatches += 1
                for index in weak_indexes[:5]:
                    dedupe_candidates.append(_candidate_diagnostic(
                        central_rows[index],
                        local_row,
                        decision="kept_separate",
                        reason="weak_identity_price_mismatch",
                        identity_strength="weak",
                    ))

        local_only += 1
        local_row.provenance = {
            "sources": ["edeka_local_fellenzer"],
            "local": local_row.provenance,
            "dedupe_decision": {
                "decision": "kept_separate",
                "reason": (
                    "possible_variant_or_price_difference"
                    if _weak_identity_key(local_row) in central_by_weak
                    else "no_matching_central_identity"
                ),
            },
        }
        merged_rows.append(local_row)

    merged_rows, cross_dupes = quality_deduplicate(merged_rows)
    central_count = len(central_rows)
    local_count = len(local_rows)
    local_artifacts = dict(local.artifacts or {}) if local else {}
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
        "duplicate_candidate_count": len(dedupe_candidates),
        "weak_price_mismatch_count": weak_price_mismatches,
        "ambiguous_candidate_count": ambiguous_candidates,
        "local_fetch_method": local_artifacts.get("local_fetch_method"),
        "local_fetch_http_status": local_artifacts.get("local_fetch_http_status"),
        "local_fetch_final_host": local_artifacts.get("local_fetch_final_host"),
        "local_fetch_block_reason": local_artifacts.get("local_fetch_block_reason"),
    }

    artifacts = dict(central.artifacts or {})
    artifacts.update({
        "source_breakdown": source_breakdown,
        "dedupe_candidates": dedupe_candidates[:100],
        "central_collector_path": central.collector_path,
        "local_collector_path": local.collector_path if local else None,
        "central_source_url": central.source_url,
        "central_market_page_url": central.final_url,
        "local_source_url": local.source_url if local else None,
        "local_error": local_artifacts.get("local_error") if local else None,
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
            f"Preis-Konflikte {price_conflicts}, mögliche Varianten {weak_price_mismatches}"
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
        artifacts = dict(exc.artifacts or {})
        artifacts.update({
            "local_error": exc.error_type,
            "local_error_message": str(exc),
            "local_fetch_block_reason": artifacts.get("local_fetch_block_reason") or exc.error_type,
        })
        return WebAuditResult(
            offers=[], source_url="https://edeka-fellenzer.de/angebote/",
            final_url="https://edeka-fellenzer.de/angebote/",
            collector_path="edeka_local_fellenzer_unavailable", raw_count=0, status="partial",
            message=f"Lokale Fellenzer-Quelle nicht verfügbar: {exc.error_type}",
            artifacts=artifacts,
        )
    result.artifacts = dict(result.artifacts or {})
    result.artifacts["market_id"] = _market_id(store)
    result.artifacts["source_role"] = "local_supplement"
    return result


def fetch_combined_edeka(store: Store) -> WebAuditResult:
    central = fetch_central_edeka(store)
    local = fetch_local_edeka(store)
    return merge_edeka_sources(central, local)
