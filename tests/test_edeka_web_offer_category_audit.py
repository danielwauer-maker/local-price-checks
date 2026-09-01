from __future__ import annotations

import httpx

from app.edeka_web_offer_category_audit import _extract_categories, _fetch_all_categories
from app.edeka_web_offer_api_audit import EDEKA_OFFERS_ENDPOINT
from app.models import Store


def _store() -> Store:
    return Store(
        id=77,
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 35",
        external_id="071378",
        active=True,
    )


def _response(payload, params) -> httpx.Response:
    request = httpx.Request("GET", EDEKA_OFFERS_ENDPOINT, params=params)
    return httpx.Response(200, json=payload, request=request)


def test_extract_categories_from_facet_map_and_docs():
    payload = {
        "docs": [{"warengruppe": "Obst & Gemüse"}],
        "facet_counts": {"warengruppe": {"Obst & Gemüse": 80, "Molkerei": 70, "Getränke": 74}},
    }
    categories = _extract_categories(payload, payload["docs"])
    assert "Obst & Gemüse" in categories
    assert "Molkerei" in categories
    assert "Getränke" in categories


def test_category_aware_collector_combines_all_categories_to_224():
    categories = {
        "Obst & Gemüse": 80,
        "Molkerei": 70,
        "Getränke": 74,
    }
    rows_by_category = {
        category: [
            {
                "angebotid": f"{category}-{i}",
                "titel": f"{category} Artikel {i} 1 kg",
                "preis": 1.0 + i / 100,
                "warengruppe": category,
            }
            for i in range(count)
        ]
        for category, count in categories.items()
    }

    def fake_get(url, **kwargs):
        params = dict(kwargs["params"])
        if set(params) == {"marketId"}:
            payload = {
                "docs": rows_by_category["Obst & Gemüse"][:10],
                "facet_counts": {"warengruppe": categories},
            }
            return _response(payload, params)

        category = params.get("category") or params.get("warengruppe") or params.get("categoryName") or params.get("wg")
        if category not in rows_by_category:
            return _response({"docs": []}, params)
        all_rows = rows_by_category[category]

        # Only category=... is the accepted category selector in this fixture.
        if "category" not in params:
            return _response({"docs": rows_by_category["Obst & Gemüse"][:10]}, params)

        offset = int(params.get("offset", 0))
        if "offset" in params and "limit" in params:
            page = all_rows[offset:offset + 10]
        elif set(params) == {"marketId", "category"}:
            page = all_rows[:10]
        else:
            page = all_rows[:10]
        return _response({"docs": page, "numFound": len(all_rows)}, params)

    result = _fetch_all_categories(_store(), http_get=fake_get)
    assert result.raw_count == 224
    assert len(result.offers) == 224
    assert result.collector_path == "edeka_web_offer_api_category"
    assert result.artifacts["category_count"] == 3
    assert {row["category"] for row in result.artifacts["category_meta"]} == set(categories)
    assert sum(row["unique_added"] for row in result.artifacts["category_meta"]) == 224


def test_categories_are_deduplicated_across_sections():
    shared = {
        "angebotid": "shared-1",
        "titel": "Gemeinsames Angebot 1 kg",
        "preis": 1.99,
        "warengruppe": "A",
    }
    payload = {
        "facet_counts": {"warengruppe": {"A": 1, "B": 1}},
        "docs": [shared],
    }
    assert _extract_categories(payload, payload["docs"])[:2] == ["A", "B"]
