from __future__ import annotations

import json
import time
from urllib.parse import urlencode

import httpx

from .config import settings
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

PAGE_SIZE = 50
MAX_PAGES = 100


def _request(store: Store, params: dict, http_get=httpx.get) -> tuple[list[dict], dict, httpx.Response]:
    try:
        response = http_get(
            EDEKA_OFFERS_ENDPOINT,
            params=params,
            follow_redirects=True,
            timeout=settings.collector_timeout_seconds,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                "User-Agent": "Spareno-Web-Audit/1.0",
            },
        )
    except httpx.TimeoutException as exc:
        raise WebAuditError("timeout", f"EDEKA Angebots-API Timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise WebAuditError("endpoint_changed", f"EDEKA Angebots-API HTTP-Fehler: {exc}") from exc

    diagnostics = {
        "fetch_mode": "edeka-web-api-adaptive-pagination",
        "api_url": str(response.url),
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "response_bytes": len(response.content),
    }
    if response.status_code in {401, 403, 429}:
        raise WebAuditError(
            "blocked",
            f"EDEKA Angebots-API antwortet mit HTTP {response.status_code}; keine Umgehung wird versucht.",
            diagnostics,
        )
    try:
        response.raise_for_status()
        payload = response.json()
    except ValueError as exc:
        raise WebAuditError("invalid_json", "EDEKA Angebots-API lieferte kein gültiges JSON.", diagnostics) from exc
    except httpx.HTTPStatusError as exc:
        raise WebAuditError("endpoint_changed", f"EDEKA Angebots-API antwortet mit HTTP {response.status_code}.", diagnostics) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("docs"), list):
        diagnostics["response_keys"] = sorted(str(key) for key in payload.keys())[:100] if isinstance(payload, dict) else []
        raise WebAuditError("endpoint_changed", "EDEKA Angebots-API enthält kein erwartetes 'docs'-Array.", diagnostics)
    return [row for row in payload["docs"] if isinstance(row, dict)], payload, response


def _strategy_params(name: str, market_id: str, page: int, offset: int) -> dict:
    base = {"marketId": market_id}
    if name == "offset_limit":
        return {**base, "offset": offset, "limit": PAGE_SIZE}
    if name == "offset_rows":
        return {**base, "offset": offset, "rows": PAGE_SIZE}
    if name == "start_limit":
        return {**base, "start": offset, "limit": PAGE_SIZE}
    if name == "start_rows":
        return {**base, "start": offset, "rows": PAGE_SIZE}
    if name == "page_limit_1":
        return {**base, "page": page + 1, "limit": PAGE_SIZE}
    if name == "page_size_1":
        return {**base, "page": page + 1, "size": PAGE_SIZE}
    if name == "page_number_size":
        return {**base, "pageNumber": page + 1, "pageSize": PAGE_SIZE}
    if name == "from_size":
        return {**base, "from": offset, "size": PAGE_SIZE}
    raise ValueError(name)


def _new_rows(docs: list[dict], seen: set[str]) -> list[dict]:
    result = []
    for row in docs:
        signature = _doc_signature(row)
        if signature in seen:
            continue
        result.append(row)
    return result


def _fetch_all_edeka_api(store: Store, http_get=httpx.get) -> WebAuditResult:
    if not store.external_id:
        raise WebAuditError("browser_required", "EDEKA benötigt eine verifizierte Markt-ID für den Angebots-API-Audit.")
    market_id = "".join(character for character in str(store.external_id).strip() if character.isdigit())
    if not market_id:
        raise WebAuditError("browser_required", "EDEKA-Markt-ID enthält keine nutzbare numerische ID.")

    started = time.monotonic()
    first_params = {"marketId": market_id}
    first_docs, first_payload, first_response = _request(store, first_params, http_get=http_get)
    if not first_docs:
        raise WebAuditError("empty", "EDEKA Angebots-API lieferte keine Angebotsdatensätze.")

    all_docs = list(first_docs)
    seen = {_doc_signature(row) for row in first_docs}
    probe_log = []
    strategy = None
    second_docs = None
    second_payload = None
    second_response = None

    strategies = (
        "offset_limit", "offset_rows", "start_limit", "start_rows",
        "page_limit_1", "page_size_1", "page_number_size", "from_size",
    )
    for candidate in strategies:
        params = _strategy_params(candidate, market_id, 1, len(first_docs))
        docs, payload, response = _request(store, params, http_get=http_get)
        fresh = _new_rows(docs, seen)
        probe_log.append({
            "strategy": candidate,
            "params": params,
            "received_docs": len(docs),
            "new_docs": len(fresh),
            "response_keys": sorted(str(key) for key in payload.keys())[:50],
        })
        if fresh:
            strategy = candidate
            second_docs = docs
            second_payload = payload
            second_response = response
            break

    if strategy is None:
        raise WebAuditError(
            "endpoint_changed",
            "EDEKA Angebots-API liefert nur den ersten Teilbestand und keines der geprüften Pagination-Schemata erzeugt neue Angebots-IDs. Der Lauf wird absichtlich nicht als vollständig gespeichert.",
            {
                "fetch_mode": "edeka-web-api-adaptive-pagination",
                "first_docs": len(first_docs),
                "probe_log": probe_log,
                "first_response_keys": sorted(str(key) for key in first_payload.keys())[:100],
            },
        )

    pages = [{"page": 1, "received_docs": len(first_docs), "new_docs": len(first_docs), "params": first_params}]
    total_bytes = len(first_response.content)
    final_response = first_response
    offset = len(first_docs)
    page = 1

    assert second_docs is not None and second_payload is not None and second_response is not None
    current_docs = second_docs
    current_payload = second_payload
    current_response = second_response

    while page < MAX_PAGES:
        fresh = _new_rows(current_docs, seen)
        for row in fresh:
            seen.add(_doc_signature(row))
            all_docs.append(row)
        pages.append({
            "page": page + 1,
            "received_docs": len(current_docs),
            "new_docs": len(fresh),
            "params": _strategy_params(strategy, market_id, page, offset),
        })
        total_bytes += len(current_response.content)
        final_response = current_response
        if not current_docs or not fresh:
            break

        offset = len(all_docs)
        page += 1
        params = _strategy_params(strategy, market_id, page, offset)
        current_docs, current_payload, current_response = _request(store, params, http_get=http_get)
    else:
        raise WebAuditError(
            "endpoint_changed",
            f"EDEKA Pagination überschritt das Sicherheitslimit von {MAX_PAGES} Seiten.",
            {"strategy": strategy, "pages": pages},
        )

    source_url = f"{EDEKA_OFFERS_ENDPOINT}?{urlencode({'marketId': market_id})}"
    raw = [_parse_edeka_doc(row, store, source_url) for row in all_docs]
    raw = [row for row in raw if row is not None]
    offers, duplicates = quality_deduplicate(raw)
    if not offers:
        raise WebAuditError("empty", "EDEKA Angebots-API lieferte keine validen Angebotsdatensätze.")

    diagnostics = {
        "fetch_mode": "edeka-web-api-adaptive-pagination",
        "api_url": source_url,
        "pagination_strategy": strategy,
        "probe_log": probe_log,
        "pages_fetched": len(pages),
        "pages": pages,
        "docs_count": len(all_docs),
        "parsed_count": len(raw),
        "response_bytes": total_bytes,
        "http_status": final_response.status_code,
        "final_url": str(final_response.url),
        "content_type": final_response.headers.get("content-type", ""),
        "network_payloads": [],
        "console_errors": [],
        "failed_requests": [],
    }
    return WebAuditResult(
        offers=offers,
        source_url=source_url,
        final_url=str(final_response.url),
        collector_path="edeka_web_offer_api_v2",
        raw_count=len(raw),
        duplicate_count=duplicates,
        message=f"{round((time.monotonic() - started) * 1000)} ms via EDEKA Web API ({len(pages)} Seiten; {strategy})",
        artifacts=diagnostics,
    )


def run_web_offer_audit(db, store: Store, period_key: str = "current", source_url: str | None = None):
    if store.retailer != "EDEKA":
        return run_legacy_edeka_audit(db, store, period_key=period_key, source_url=source_url)
    try:
        result = _fetch_all_edeka_api(store)
        return _persist_edeka_result(db, store, period_key, result)
    except WebAuditError as exc:
        return _persist_edeka_failure(db, store, period_key, exc)
