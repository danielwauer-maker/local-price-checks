from __future__ import annotations

import re
import time
from urllib.parse import urlencode

import httpx

from .config import settings
from .edeka_web_offer_api_audit import EDEKA_OFFERS_ENDPOINT, _parse_edeka_doc
from .models import Store
from .web_offer_audit import WebAuditError, WebAuditResult
from .web_offer_audit_runtime import quality_deduplicate

EDEKA_MARKETSEARCH_ENDPOINT = "https://www.edeka.de/api/marketsearch/markets"


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _candidate_value(candidate: dict, *keys: str) -> str:
    for key in keys:
        value = candidate.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def _candidate_score(candidate: dict, store: Store) -> int:
    score = 0
    name = _norm(_candidate_value(candidate, "name", "marketName", "title"))
    postal = _norm(_candidate_value(candidate, "zip", "postalCode", "postcode", "plz"))
    city = _norm(_candidate_value(candidate, "city", "town", "ort"))
    address = _norm(_candidate_value(candidate, "address", "street", "streetAddress", "strasse"))

    target_name = _norm(store.name)
    target_postal = _norm(store.postal_code)
    target_city = _norm(store.city)
    target_address = _norm(store.address)

    if target_postal and postal == target_postal:
        score += 100
    if target_city and city == target_city:
        score += 40
    if target_name and name == target_name:
        score += 80
    elif target_name and name and (target_name in name or name in target_name):
        score += 35
    if target_address and address:
        if target_address == address:
            score += 120
        elif target_address in address or address in target_address:
            score += 60
    return score


def resolve_offers_market_id(store: Store, http_get=httpx.get) -> tuple[str, dict]:
    search_terms = [
        f"{store.postal_code or ''} {store.city or ''}".strip(),
        str(store.city or "").strip(),
        str(store.postal_code or "").strip(),
    ]
    attempts: list[dict] = []
    best: tuple[int, str, dict] | None = None

    for term in dict.fromkeys(term for term in search_terms if term):
        try:
            response = http_get(
                EDEKA_MARKETSEARCH_ENDPOINT,
                params={"searchstring": term},
                follow_redirects=True,
                timeout=settings.collector_timeout_seconds,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "de-DE,de;q=0.9",
                    "User-Agent": "Spareno-Web-Audit/1.0",
                },
            )
        except httpx.HTTPError as exc:
            attempts.append({"searchstring": term, "error": str(exc)})
            continue

        meta = {
            "searchstring": term,
            "status": response.status_code,
            "final_url": str(response.url),
            "content_type": response.headers.get("content-type", ""),
        }
        attempts.append(meta)
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except ValueError:
            continue
        markets = payload.get("markets") if isinstance(payload, dict) else None
        if not isinstance(markets, list):
            continue

        for candidate in markets:
            if not isinstance(candidate, dict):
                continue
            candidate_id = _candidate_value(candidate, "id", "marketId", "marketID")
            if not candidate_id:
                continue
            score = _candidate_score(candidate, store)
            if best is None or score > best[0]:
                best = (score, candidate_id, candidate)

        if best is not None and best[0] >= 200:
            break

    if best is None or best[0] < 100:
        raise WebAuditError(
            "market_identity_unresolved",
            "EDEKA-Marktsuche konnte keinen ausreichend eindeutigen Markt für den Angebotsfeed auflösen.",
            {"marketsearch_attempts": attempts, "best_score": best[0] if best else None},
        )

    score, market_id, candidate = best
    diagnostics = {
        "marketsearch_attempts": attempts,
        "resolved_offer_market_id": market_id,
        "resolved_market_score": score,
        "resolved_market_name": _candidate_value(candidate, "name", "marketName", "title"),
        "resolved_market_postal_code": _candidate_value(candidate, "zip", "postalCode", "postcode", "plz"),
        "resolved_market_city": _candidate_value(candidate, "city", "town", "ort"),
        "resolved_market_address": _candidate_value(candidate, "address", "street", "streetAddress", "strasse"),
    }
    return market_id, diagnostics


def fetch_resolved_market_offers(store: Store, http_get=httpx.get) -> WebAuditResult:
    started = time.monotonic()
    market_id, diagnostics = resolve_offers_market_id(store, http_get=http_get)
    params = {"marketId": market_id, "limit": 99999}
    request_url = f"{EDEKA_OFFERS_ENDPOINT}?{urlencode(params)}"
    try:
        response = http_get(
            EDEKA_OFFERS_ENDPOINT,
            params=params,
            follow_redirects=True,
            timeout=settings.collector_timeout_seconds,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9",
                "User-Agent": "Spareno-Web-Audit/1.0",
            },
        )
    except httpx.HTTPError as exc:
        raise WebAuditError(
            "endpoint_changed",
            f"EDEKA Angebotsfeed konnte nach Markt-ID-Auflösung nicht geladen werden: {exc}",
            diagnostics,
        ) from exc

    diagnostics.update({
        "collector_endpoint_url": request_url,
        "http_status": response.status_code,
        "final_endpoint_url": str(response.url),
        "content_type": response.headers.get("content-type", ""),
        "response_bytes": len(response.content),
    })
    if response.status_code in {401, 403, 429}:
        raise WebAuditError(
            "blocked",
            f"EDEKA Angebotsfeed antwortet mit HTTP {response.status_code}.",
            diagnostics,
        )
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPStatusError, ValueError) as exc:
        raise WebAuditError("endpoint_changed", "EDEKA Angebotsfeed lieferte keine verwertbare JSON-Antwort.", diagnostics) from exc

    docs = payload.get("docs") if isinstance(payload, dict) else None
    if not isinstance(docs, list):
        raise WebAuditError("endpoint_changed", "EDEKA Angebotsfeed enthält kein 'docs'-Array.", diagnostics)

    raw = [_parse_edeka_doc(row, store, request_url) for row in docs if isinstance(row, dict)]
    raw = [row for row in raw if row is not None]
    offers, duplicates = quality_deduplicate(raw)
    diagnostics.update({
        "response_docs": len(docs),
        "parsed_count": len(raw),
        "unique_count": len(offers),
    })
    if not offers:
        raise WebAuditError("empty", "EDEKA Angebotsfeed lieferte keine validen Angebote.", diagnostics)

    return WebAuditResult(
        offers=offers,
        source_url=request_url,
        final_url=str(response.url),
        collector_path="edeka_marketsearch_resolved_offers",
        raw_count=len(raw),
        duplicate_count=duplicates,
        message=(
            f"EDEKA Markt-ID via offizieller Marktsuche aufgelöst: {market_id}; "
            f"{len(offers)} unique Angebote in {round((time.monotonic() - started) * 1000)} ms"
        ),
        artifacts=diagnostics,
    )
