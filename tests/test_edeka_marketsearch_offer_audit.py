from __future__ import annotations

import httpx

from app.edeka_marketsearch_offer_audit import fetch_resolved_market_offers, resolve_offers_market_id
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


def _response(url: str, payload: dict) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(200, request=request, json=payload)


def test_marketsearch_resolver_prefers_exact_postcode_city_address_match():
    def fake_get(url, params=None, **kwargs):
        assert url.endswith("/api/marketsearch/markets")
        return _response(
            f"{url}?searchstring=56305+Puderbach",
            {
                "markets": [
                    {
                        "id": "wrong-market",
                        "name": "EDEKA Andere Filiale",
                        "postalCode": "56305",
                        "city": "Puderbach",
                        "address": "Andere Straße 1",
                    },
                    {
                        "id": "internal-fellenzer-id",
                        "name": "EDEKA Fellenzer",
                        "postalCode": "56305",
                        "city": "Puderbach",
                        "address": "Urbacher Straße 35",
                    },
                ]
            },
        )

    market_id, diagnostics = resolve_offers_market_id(_store(), http_get=fake_get)
    assert market_id == "internal-fellenzer-id"
    assert diagnostics["resolved_market_score"] >= 300


def test_resolved_market_id_is_used_for_limit_99999_offer_request():
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, dict(params or {})))
        if url.endswith("/api/marketsearch/markets"):
            return _response(
                f"{url}?searchstring=56305+Puderbach",
                {
                    "markets": [
                        {
                            "id": "offer-market-4711",
                            "name": "EDEKA Fellenzer",
                            "postalCode": "56305",
                            "city": "Puderbach",
                            "address": "Urbacher Straße 35",
                        }
                    ]
                },
            )
        assert url.endswith("/eh/service/eh/offers")
        assert params == {"marketId": "offer-market-4711", "limit": 99999}
        docs = [
            {
                "angebotid": f"offer-{index}",
                "titel": f"Produkt {index}",
                "preis": 1.0 + index / 100,
                "beschreibung": "500 g Packung",
            }
            for index in range(224)
        ]
        return _response(
            f"{url}?marketId=offer-market-4711&limit=99999",
            {"docs": docs},
        )

    result = fetch_resolved_market_offers(_store(), http_get=fake_get)
    assert result.collector_path == "edeka_marketsearch_resolved_offers"
    assert result.raw_count == 224
    assert len(result.offers) == 224
    assert result.artifacts["resolved_offer_market_id"] == "offer-market-4711"
    assert result.artifacts["response_docs"] == 224
    assert calls[-1][1] == {"marketId": "offer-market-4711", "limit": 99999}
