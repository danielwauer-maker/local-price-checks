from __future__ import annotations

import json

from .edeka_multi_source_audit import fetch_combined_edeka
from .edeka_web_offer_api_audit import (
    _persist_edeka_failure,
    _persist_edeka_result,
    run_web_offer_audit as run_legacy_edeka_audit,
)
from .models import Store
from .web_offer_audit import WebAuditError


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
    run.comparison_json = json.dumps(comparison, ensure_ascii=False)
    db.commit()
    db.refresh(run)


def run_web_offer_audit(db, store: Store, period_key: str = "current", source_url: str | None = None):
    """Run EDEKA audit as central-primary plus optional local supplement.

    The central EDEKA market source is always collected first.  For verified
    markets with an official local merchant source (currently Fellenzer
    071378), local offers are added afterwards and conservative cross-source
    deduplication keeps overlaps visible only once.  No path writes public
    Offer rows.
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
