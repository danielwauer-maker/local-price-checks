from __future__ import annotations

import httpx
import pytest

from app.edeka_web_offer_api_audit_v2 import _fetch_all_edeka_api
from app.edeka_web_offer_api_audit import EDEKA_OFFERS_ENDPOINT
from app.models import Store
from app.web_offer_audit import WebAuditError


def _store() -> Store:
    return Store(
        id=77,
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 35",
        external_id="071378",
        source_url="https://www.edeka.de/angebote/?selectedMarktID=071378",
        active=True,
    )


def _response(payload, params) -> httpx.Response:
    request = httpx.Request("GET", EDEKA_OFFERS_ENDPOINT, params=params)
    return httpx.Response(200, json=payload, request=request)


def test_adaptive_pagination_selects_offset_limit_and_reads_every_offer():
    rows = [{"angebotid": str(i), "titel": f"Artikel {i} 1 kg", "preis": 1.0} for i in range(224)]
    calls = []

    def fake_get(url, **kwargs):
        params = kwargs["params"]
        calls.append(dict(params))
        if set(params) == {"marketId"}:
            page = rows[:10]
        elif "offset" in params and "limit" in params:
            offset = int(params["offset"])
            page = rows[offset:offset + 10]
        else:
            page = rows[:10]
        return _response({"docs": page, "numFound": 10}, params)

    result = _fetch_all_edeka_api(_store(), http_get=fake_get)
    assert result.raw_count == 224
    assert len(result.offers) == 224
    assert result.artifacts["pagination_strategy"] == "offset_limit"
    assert result.artifacts["pages_fetched"] >= 23
    assert calls[0] == {"marketId": "071378"}
    assert any(call.get("offset") == 10 and "limit" in call for call in calls)


def test_adaptive_pagination_does_not_accept_repeated_first_page_as_complete():
    docs = [{"angebotid": str(i), "titel": f"Artikel {i} 1 kg", "preis": 1.0} for i in range(10)]

    def fake_get(url, **kwargs):
        return _response({"docs": docs, "numFound": 10}, kwargs["params"])

    with pytest.raises(WebAuditError) as caught:
        _fetch_all_edeka_api(_store(), http_get=fake_get)
    assert caught.value.error_type == "endpoint_changed"
    assert "Teilbestand" in str(caught.value)
    assert len(caught.value.artifacts["probe_log"]) >= 4


def test_adaptive_pagination_preserves_leading_zero_market_id():
    observed = []
    rows = [
        {"angebotid": "1", "titel": "Artikel 1 1 kg", "preis": 1.0},
        {"angebotid": "2", "titel": "Artikel 2 1 kg", "preis": 1.1},
    ]

    def fake_get(url, **kwargs):
        params = kwargs["params"]
        observed.append(dict(params))
        if set(params) == {"marketId"}:
            return _response({"docs": rows[:1]}, params)
        if "offset" in params and "limit" in params and int(params["offset"]) == 1:
            return _response({"docs": rows[1:]}, params)
        return _response({"docs": []}, params)

    result = _fetch_all_edeka_api(_store(), http_get=fake_get)
    assert result.raw_count == 2
    assert all(call["marketId"] == "071378" for call in observed)
