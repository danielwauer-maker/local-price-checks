from __future__ import annotations

from math import ceil
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .engine_v140.browser_fetch import browser_fetch
from .models import Store
from .web_offer_audit import WebAuditResult
from .web_offer_audit_runtime import ReviewedEdekaWebOfferAdapter


KNOWN_REFERENCE_COUNTS = {"071378": 224}


def central_market_page_url(market_id: str) -> str:
    return f"https://www.edeka.de/maerkte/{market_id}/angebote/"


def _category_diagnostics(html: str, market_id: str) -> dict:
    """Describe EDEKA's real server-rendered load-more surface."""
    soup = BeautifulSoup(html, "html.parser")
    categories = []
    for group in soup.select("load-more"):
        offer_list = group.find("ul", id=lambda value: bool(value and value.startswith("filter-results-group-list-")))
        if offer_list is None:
            continue
        items = offer_list.find_all("li", id=lambda value: bool(value and value.startswith("filter-results-item-")), recursive=False)
        shown = sum(item.get("data-show-by-load-more") == "true" for item in items)
        categories.append({
            "category": offer_list.get("id", "").removeprefix("filter-results-group-list-"),
            "server_rendered_count": len(items),
            "initial_visible_count": shown,
            "initial_hidden_count": len(items) - shown,
            "batch_size": int(group.get("data-max-items") or 0),
            "has_load_more_button": group.select_one("button#load-more-button") is not None,
            "required_visibility_batches": max(ceil(len(items) / max(int(group.get("data-max-items") or 1), 1)) - 1, 0),
            "offer_ids": [
                link.get("href", "").lstrip("#")
                for item in items
                for link in item.select('article a[href^="#angebot-"]')[:1]
            ],
        })

    offer_targets = {
        link.get("href", "").lstrip("#")
        for link in soup.select('a[href^="#angebot-"]')
        if link.get("href")
    }
    category_offer_ids = {
        item.get("id", "").removeprefix("filter-results-item-")
        for item in soup.select('[id^="filter-results-item-"]')
    }
    return {
        "load_more_mechanism": "server_rendered_dom_data_attribute_toggle",
        "central_requests": 1,
        "categories_detected": len(categories),
        "categories": categories,
        "central_category_counts": {row["category"]: row["server_rendered_count"] for row in categories},
        "server_rendered_category_count": len(category_offer_ids),
        "server_rendered_offer_count": len(offer_targets),
        "featured_offer_count": max(len(offer_targets) - len(category_offer_ids), 0),
        "known_reference_count": KNOWN_REFERENCE_COUNTS.get(market_id),
    }


def fetch_central_market_page(store: Store, period_key: str = "current", fetcher=browser_fetch) -> WebAuditResult:
    market_id = "".join(character for character in str(store.external_id or "") if character.isdigit())
    if not market_id:
        from .web_offer_audit import WebAuditError
        raise WebAuditError("browser_required", "EDEKA-Zentralquelle benötigt eine verifizierte numerische Markt-ID.")
    source_url = central_market_page_url(market_id)
    result = ReviewedEdekaWebOfferAdapter(fetcher=fetcher).collect(store, source_url, period_key)
    diagnostics = _category_diagnostics(str(result.artifacts.get("html") or ""), market_id)
    parsed_count = len(result.offers)
    parsed_ids = {row.external_offer_id for row in result.offers if row.external_offer_id}
    dom_ids = {
        offer_id
        for category in diagnostics["categories"]
        for offer_id in category.pop("offer_ids")
    }
    soup = BeautifulSoup(str(result.artifacts.get("html") or ""), "html.parser")
    dom_ids.update(
        link.get("href", "").lstrip("#")
        for link in soup.select('a[href^="#angebot-"]')
        if link.get("href")
    )
    for category in diagnostics["categories"]:
        slug = category["category"]
        category_ids = {
            link.get("href", "").lstrip("#")
            for link in soup.select(
                f'#filter-results-group-list-{slug} > li article a[href^="#angebot-"]'
            )
            if link.get("href")
        }
        category["parsed_count"] = len(category_ids & parsed_ids)
        category["completed"] = bool(category_ids) and category_ids <= parsed_ids
    rendered_count = diagnostics["server_rendered_offer_count"]
    reference = diagnostics["known_reference_count"]
    categories_complete = bool(diagnostics["categories_detected"]) and all(
        row["completed"] and row["server_rendered_count"] >= row["initial_visible_count"] and row["batch_size"] > 0
        for row in diagnostics["categories"]
    )
    complete = (
        categories_complete
        and rendered_count > 0
        and dom_ids <= parsed_ids
        and (reference is None or parsed_count >= reference)
    )
    diagnostics.update({
        "parsed_central_count": parsed_count,
        "unparsed_dom_offer_count": len(dom_ids - parsed_ids),
        "unexpected_parsed_offer_count": len(parsed_ids - dom_ids),
        "central_completeness": "complete" if complete else "partial",
        "central_completeness_reason": (
            "Alle serverseitig gerenderten Angebots-IDs einschließlich versteckter Kategorien wurden geparst."
            if complete else "DOM-/Parser-Anzahl oder bekannte Referenz wurde nicht vollständig erreicht."
        ),
    })
    diagnostics.update({
        "central_categories_detected": diagnostics["categories_detected"],
        "central_categories_completed": sum(row["completed"] for row in diagnostics["categories"]),
        "central_raw_count": result.raw_count,
        "central_unique_count": parsed_count,
        "central_expected_reference_count": reference,
        "known_reference_visible_count": reference,
        "central_completeness_status": diagnostics["central_completeness"],
        "central_fetch_method": (
            "DOM_DIRECT"
            if result.artifacts.get("fetch_mode") == "http-edeka-server-rendered"
            else "PLAYWRIGHT_DOM"
        ),
        "central_fetch_http_status": result.artifacts.get("http_status"),
        "central_fetch_http_version": result.artifacts.get("http_version"),
        "central_fetch_final_host": result.artifacts.get("final_host") or (
            urlparse(result.final_url or source_url).hostname or ""
        ).lower(),
        "central_fetch_response_headers": result.artifacts.get("response_headers", {}),
        "central_fetch_redirect_chain": result.artifacts.get("redirect_chain", []),
        "central_fetch_attempts": result.artifacts.get("fetch_attempts", []),
        "central_fetch_block_reason": result.artifacts.get("block_reason"),
        "central_fetch_fallback_used": bool(result.artifacts.get("fallback_used")),
        "central_structured_endpoint": None,
        "central_dom_count": rendered_count,
        "central_parsed_count": parsed_count,
        "central_reference_count": reference,
    })
    for offer in result.offers:
        offer.provenance = {
            "sources": ["edeka_central"],
            "central": offer.provenance,
        }
    result.artifacts.update(diagnostics)
    result.artifacts.update({
        "market_page_id": market_id,
        "source_role": "central_primary",
        "collector_endpoint_url": source_url,
    })
    result.collector_path = "edeka_central_market_page_dom"
    result.status = "success" if complete else "partial"
    result.message = (
        f"EDEKA Zentral-DOM: {parsed_count} Angebote, {diagnostics['categories_detected']} Kategorien, "
        f"Completeness={diagnostics['central_completeness']}; Mehr laden ist ein clientseitiger Sichtbarkeits-Toggle."
    )
    return result
