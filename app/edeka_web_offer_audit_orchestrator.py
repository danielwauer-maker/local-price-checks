from __future__ import annotations

import json
import re

from .edeka_multi_source_audit import fetch_combined_edeka
from .edeka_web_offer_api_audit import (
    _persist_edeka_failure,
    _persist_edeka_result,
    run_web_offer_audit as run_legacy_edeka_audit,
)
from .models import Store
from .web_offer_audit import WebAuditError, WebOfferRecord


def _normalized_display_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", (value or "").casefold()).strip()


def _single_source_label(offer: WebOfferRecord) -> str | None:
    provenance = offer.provenance or {}
    sources = provenance.get("sources")
    if isinstance(sources, list):
        normalized = {str(source) for source in sources if source}
        if len(normalized) != 1:
            return None
        source = next(iter(normalized))
        if source == "edeka_central":
            return "central"
        if source == "edeka_local_fellenzer":
            return "local"

    source = str(provenance.get("source") or "").casefold()
    if source == "official_store_site" or "fellenzer" in source:
        return "local"
    if "central" in source or source in {"central_api", "edeka_web_api"}:
        return "central"

    url = (offer.source_url or "").casefold()
    if "edeka-fellenzer.de" in url:
        return "local"
    if "edeka.de" in url:
        return "central"
    return None


def _same_source_variant_candidates(offers: list[WebOfferRecord]) -> list[dict]:
    """Describe same-name variants inside one source without changing any rows.

    This deliberately does not merge anything. It only makes cases such as two
    central "Himbeeren" cards with different prices or images visible in the
    admin audit so a human can verify whether they are genuine variants.
    """
    groups: dict[tuple[str, str], list[WebOfferRecord]] = {}
    for offer in offers:
        source = _single_source_label(offer)
        name_key = _normalized_display_name(offer.name)
        if not source or not name_key:
            continue
        groups.setdefault((source, name_key), []).append(offer)

    candidates: list[dict] = []
    for (source, _), rows in groups.items():
        if len(rows) < 2:
            continue
        for left_index, left in enumerate(rows[:-1]):
            for right in rows[left_index + 1 :]:
                price_differs = (
                    left.price is not None
                    and right.price is not None
                    and abs(left.price - right.price) >= 0.005
                )
                image_differs = bool(left.image_url or right.image_url) and left.image_url != right.image_url
                if not price_differs and not image_differs:
                    continue

                if price_differs and image_differs:
                    reason = "same_source_same_name_price_and_image_variant"
                elif price_differs:
                    reason = "same_source_same_name_price_variant"
                else:
                    reason = "same_source_same_name_image_variant"

                label = "Central" if source == "central" else "Local"
                candidates.append({
                    "decision": "kept_separate",
                    "reason": reason,
                    "identity_strength": "same_source_name_diagnostic",
                    "source": source,
                    "central_offer_id": left.external_offer_id,
                    "local_offer_id": right.external_offer_id,
                    "central_product_id": left.external_product_id,
                    "local_product_id": right.external_product_id,
                    "central_ean": left.ean,
                    "local_ean": right.ean,
                    "central_name": f"[{label} A] {left.name}",
                    "local_name": f"[{label} B] {right.name}",
                    "central_price": left.price,
                    "local_price": right.price,
                    "central_quantity": left.packaging_text or left.quantity,
                    "local_quantity": right.packaging_text or right.quantity,
                    "central_image_url": left.image_url,
                    "local_image_url": right.image_url,
                })
                if len(candidates) >= 100:
                    return candidates
    return candidates


def _attach_source_breakdown(db, run, result) -> None:
    breakdown = (result.artifacts or {}).get("source_breakdown")
    if not isinstance(breakdown, dict):
        return
    try:
        comparison = json.loads(run.comparison_json or "{}")
    except json.JSONDecodeError:
        comparison = {}
    comparison.update({key if key.startswith("source_") else f"source_{key}": value for key, value in breakdown.items()})
    # Keep the historic double-prefixed key readable for existing audit links.
    if "source_overlap" in breakdown:
        comparison["source_source_overlap"] = breakdown["source_overlap"]
    for key in (
        "central_completeness", "central_completeness_reason", "known_reference_count",
        "parsed_central_count", "server_rendered_offer_count", "server_rendered_category_count",
        "featured_offer_count", "categories_detected", "central_requests", "load_more_mechanism",
        "central_category_counts",
        "central_categories_detected", "central_categories_completed", "central_raw_count",
        "central_unique_count", "central_expected_reference_count", "known_reference_visible_count",
        "central_completeness_status", "unparsed_dom_offer_count", "unexpected_parsed_offer_count",
        "central_fetch_method", "central_fetch_http_status", "central_fetch_http_version",
        "central_fetch_final_host", "central_fetch_block_reason", "central_fetch_fallback_used",
        "central_structured_endpoint", "central_dom_count", "central_parsed_count",
        "central_reference_count", "central_fetch_response_headers", "central_fetch_redirect_chain",
    ):
        if key in (result.artifacts or {}):
            comparison[key] = result.artifacts[key]

    dedupe_candidates = (result.artifacts or {}).get("dedupe_candidates")
    source_candidates = list(dedupe_candidates) if isinstance(dedupe_candidates, list) else []
    same_source_candidates = _same_source_variant_candidates(list(result.offers))
    combined_candidates = (source_candidates + same_source_candidates)[:100]
    comparison["source_same_source_variant_count"] = len(same_source_candidates)
    comparison["source_internal_duplicate_count"] = int(result.duplicate_count or 0)
    comparison["source_duplicate_candidate_count"] = len(combined_candidates)
    comparison["source_dedupe_candidates"] = combined_candidates

    run.comparison_json = json.dumps(comparison, ensure_ascii=False)
    db.commit()
    db.refresh(run)


def run_web_offer_audit(db, store: Store, period_key: str = "current", source_url: str | None = None):
    """Run EDEKA audit as central-primary plus optional local supplement.

    The central EDEKA market source is always collected first. For verified
    markets with an official local merchant source (currently Fellenzer
    071378), local offers are added afterwards. Strong product identities may
    merge across sources even if the price differs (visible conflict); weak
    name/quantity matches only merge when the price also agrees. No path writes
    public Offer rows.
    """
    if store.retailer != "EDEKA":
        return run_legacy_edeka_audit(db, store, period_key=period_key, source_url=source_url)

    try:
        result = fetch_combined_edeka(store)
        run = _persist_edeka_result(db, store, period_key, result)
        _attach_source_breakdown(db, run, result)
        return run
    except WebAuditError as exc:
        # Never let an unexpected combined-path failure fall through to a
        # small legacy API result that could be mistaken for completeness.
        return _persist_edeka_failure(db, store, period_key, exc)
