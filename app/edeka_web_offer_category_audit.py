from __future__ import annotations

import re
import time
from urllib.parse import urlencode

import httpx

from .models import Store
from .web_offer_audit import WebAuditError, WebAuditResult
from .web_offer_audit_runtime import quality_deduplicate
from .edeka_web_offer_api_audit import (
    EDEKA_OFFERS_ENDPOINT,
    _doc_signature,
    _parse_edeka_doc,
    _persist_edeka_failure,
    _persist_edeka_result,
    run_web_offer_audit as run_legacy_edeka_audit,
)
from .edeka_web_offer_api_audit_v2 import _request

MAX_CATEGORY_PAGES = 100
PAGE_SIZE = 50
CATEGORY_PARAM_NAMES = ("category", "warengruppe", "categoryName", "wg")
PAGINATION_STRATEGIES = (
    "offset_limit", "offset_rows", "start_limit", "start_rows",
    "page_limit_1", "page_size_1", "page_number_size", "from_size",
)
_RESERVED_CATEGORY_KEYS = {
    "facet", "facets", "facet_count", "facet_counts", "facetcounts",
    "warengruppe", "category", "categoryname", "kategorie",
}


def _clean_category(value: object) -> str | None:
    if not isinstance(value, (str, int, float)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or len(text) > 120:
        return None
    return text


def _extract_categories(payload: dict, docs: list[dict]) -> list[str]:
    """Extract real category values, never facet/container field names."""
    found: list[str] = []

    def add(value: object) -> None:
        text = _clean_category(value)
        if not text or text.lower() in _RESERVED_CATEGORY_KEYS:
            return
        if text not in found:
            found.append(text)

    # First handle common facet containers explicitly. This avoids treating
    # keys such as ``warengruppe`` itself as a category value.
    for container_key in ("facet_counts", "facets", "facetCounts"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for field_name, values in container.items():
            field_l = str(field_name).lower()
            if not any(token in field_l for token in ("category", "kategorie", "warengruppe")):
                continue
            if isinstance(values, dict):
                for category_name in values.keys():
                    add(category_name)
            elif isinstance(values, list):
                for item in values:
                    if isinstance(item, (str, int, float)):
                        add(item)
                    elif isinstance(item, dict):
                        for candidate_key in ("name", "value", "label", "id", "key"):
                            if candidate_key in item:
                                add(item[candidate_key])
                                break

    # Then inspect other category-shaped response structures, but do not add
    # container/field names themselves.
    def walk(node: object, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                key_l = str(key).lower()
                if key_l in {"facet_counts", "facets", "facetcounts"}:
                    continue
                category_field = any(token in key_l for token in ("category", "kategorie", "warengruppe"))
                if category_field:
                    if isinstance(value, (str, int, float)):
                        add(value)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, (str, int, float)):
                                add(item)
                            elif isinstance(item, dict):
                                for candidate_key in ("name", "value", "label", "id", "key"):
                                    if candidate_key in item:
                                        add(item[candidate_key])
                                        break
                    elif isinstance(value, dict):
                        for category_name in value.keys():
                            add(category_name)
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:500]:
                walk(item, depth + 1)

    walk(payload)
    for row in docs:
        for key in ("warengruppe", "category", "categoryName", "kategorie"):
            if key in row:
                add(row.get(key))
    return found


def _doc_category(row: dict) -> str | None:
    for key in ("warengruppe", "category", "categoryName", "kategorie"):
        value = _clean_category(row.get(key))
        if value:
            return value
    return None


def _pagination_params(strategy: str, market_id: str, category_param: str, category: str, page: int, offset: int) -> dict:
    base = {"marketId": market_id, category_param: category}
    if strategy == "offset_limit":
        return {**base, "offset": offset, "limit": PAGE_SIZE}
    if strategy == "offset_rows":
        return {**base, "offset": offset, "rows": PAGE_SIZE}
    if strategy == "start_limit":
        return {**base, "start": offset, "limit": PAGE_SIZE}
    if strategy == "start_rows":
        return {**base, "start": offset, "rows": PAGE_SIZE}
    if strategy == "page_limit_1":
        return {**base, "page": page + 1, "limit": PAGE_SIZE}
    if strategy == "page_size_1":
        return {**base, "page": page + 1, "size": PAGE_SIZE}
    if strategy == "page_number_size":
        return {**base, "pageNumber": page + 1, "pageSize": PAGE_SIZE}
    if strategy == "from_size":
        return {**base, "from": offset, "size": PAGE_SIZE}
    raise ValueError(strategy)


def _fetch_category(store: Store, market_id: str, category: str, http_get=httpx.get) -> tuple[list[dict], dict] | None:
    probe_log: list[dict] = []
    for category_param in CATEGORY_PARAM_NAMES:
        first_params = {"marketId": market_id, category_param: category}
        docs, payload, _ = _request(store, first_params, http_get=http_get)
        category_docs = [row for row in docs if (_doc_category(row) or category) == category]
        if docs and not category_docs:
            probe_log.append({"category_param": category_param, "accepted": False, "reason": "category_mismatch"})
            continue
        if not docs:
            probe_log.append({"category_param": category_param, "accepted": False, "reason": "empty"})
            continue

        seen = {_doc_signature(row) for row in docs}
        all_docs = list(docs)
        chosen_strategy = None
        second_docs: list[dict] | None = None
        for strategy in PAGINATION_STRATEGIES:
            params = _pagination_params(strategy, market_id, category_param, category, 1, len(all_docs))
            more_docs, _, _ = _request(store, params, http_get=http_get)
            fresh = [row for row in more_docs if _doc_signature(row) not in seen]
            probe_log.append({
                "category_param": category_param,
                "strategy": strategy,
                "received": len(more_docs),
                "new": len(fresh),
            })
            if fresh:
                chosen_strategy = strategy
                second_docs = more_docs
                break

        total = payload.get("numFound") or payload.get("total") or payload.get("totalCount")
        try:
            total_int = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_int = None

        if chosen_strategy is None:
            if total_int is not None and total_int <= len(all_docs):
                return all_docs, {
                    "category": category,
                    "category_param": category_param,
                    "pagination_strategy": "single_page",
                    "count": len(all_docs),
                    "total": total_int,
                    "probe_log": probe_log,
                }
            continue

        page = 1
        current_docs = second_docs or []
        while page < MAX_CATEGORY_PAGES:
            fresh = [row for row in current_docs if _doc_signature(row) not in seen]
            if not current_docs or not fresh:
                break
            for row in fresh:
                seen.add(_doc_signature(row))
                all_docs.append(row)
            if total_int is not None and len(all_docs) >= total_int:
                break
            page += 1
            params = _pagination_params(chosen_strategy, market_id, category_param, category, page, len(all_docs))
            current_docs, _, _ = _request(store, params, http_get=http_get)
        else:
            raise WebAuditError("endpoint_changed", f"EDEKA Kategorie {category!r} überschritt das Seitenlimit.")

        return all_docs, {
            "category": category,
            "category_param": category_param,
            "pagination_strategy": chosen_strategy,
            "count": len(all_docs),
            "total": total_int,
            "probe_log": probe_log,
        }
    return None


def _fetch_all_categories(store: Store, http_get=httpx.get) -> WebAuditResult:
    if not store.external_id:
        raise WebAuditError("browser_required", "EDEKA benötigt eine verifizierte Markt-ID.")
    market_id = "".join(ch for ch in str(store.external_id).strip() if ch.isdigit())
    if not market_id:
        raise WebAuditError("browser_required", "EDEKA-Markt-ID enthält keine nutzbare numerische ID.")

    started = time.monotonic()
    seed_docs, seed_payload, seed_response = _request(store, {"marketId": market_id}, http_get=http_get)
    categories = _extract_categories(seed_payload, seed_docs)
    if not categories:
        raise WebAuditError(
            "endpoint_changed",
            "EDEKA API liefert Angebote, aber keine auswertbaren Kategorie-/Facet-Metadaten. Vollständigkeit kann nicht nachgewiesen werden.",
            {"response_keys": sorted(str(key) for key in seed_payload.keys())[:100], "seed_docs": len(seed_docs)},
        )

    all_docs: list[dict] = []
    seen: set[str] = set()
    category_meta: list[dict] = []
    failed_categories: list[str] = []
    for category in categories:
        result = _fetch_category(store, market_id, category, http_get=http_get)
        if result is None:
            failed_categories.append(category)
            continue
        docs, meta = result
        added = 0
        for row in docs:
            signature = _doc_signature(row)
            if signature in seen:
                continue
            seen.add(signature)
            all_docs.append(row)
            added += 1
        meta["unique_added"] = added
        category_meta.append(meta)

    if failed_categories:
        raise WebAuditError(
            "endpoint_changed",
            "EDEKA Kategorien konnten nicht vollständig geladen werden; der Lauf wird nicht als vollständig gespeichert.",
            {"categories": categories, "failed_categories": failed_categories, "category_meta": category_meta},
        )
    if not all_docs:
        raise WebAuditError("empty", "EDEKA Kategorien lieferten keine Angebotsdatensätze.")

    source_url = f"{EDEKA_OFFERS_ENDPOINT}?{urlencode({'marketId': market_id})}"
    raw = [_parse_edeka_doc(row, store, source_url) for row in all_docs]
    raw = [row for row in raw if row is not None]
    offers, duplicates = quality_deduplicate(raw)
    diagnostics = {
        "fetch_mode": "edeka-web-api-category-aware",
        "api_url": source_url,
        "categories": categories,
        "category_count": len(categories),
        "category_meta": category_meta,
        "docs_count": len(all_docs),
        "parsed_count": len(raw),
        "http_status": seed_response.status_code,
        "final_url": str(seed_response.url),
        "network_payloads": [],
        "console_errors": [],
        "failed_requests": [],
    }
    return WebAuditResult(
        offers=offers,
        source_url=source_url,
        final_url=str(seed_response.url),
        collector_path="edeka_web_offer_api_category",
        raw_count=len(raw),
        duplicate_count=duplicates,
        message=f"{round((time.monotonic() - started) * 1000)} ms via EDEKA Kategorien ({len(categories)} Kategorien)",
        artifacts=diagnostics,
    )


def run_web_offer_audit(db, store: Store, period_key: str = "current", source_url: str | None = None):
    if store.retailer != "EDEKA":
        return run_legacy_edeka_audit(db, store, period_key=period_key, source_url=source_url)
    try:
        result = _fetch_all_categories(store)
        return _persist_edeka_result(db, store, period_key, result)
    except WebAuditError as exc:
        return _persist_edeka_failure(db, store, period_key, exc)
