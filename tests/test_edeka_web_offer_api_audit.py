from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.edeka_web_offer_api_audit import (
    EDEKA_OFFERS_ENDPOINT,
    _fetch_edeka_api,
    _parse_edeka_doc,
)
from app.models import Store
from app.web_offer_audit import WebAuditError


def _store(external_id: str | None = "071378") -> Store:
    return Store(
        id=77,
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 35",
        external_id=external_id,
        source_url="https://www.edeka.de/angebote/?selectedMarktID=071378",
        active=True,
    )


def _response(status: int, payload, url: str = EDEKA_OFFERS_ENDPOINT) -> httpx.Response:
    request = httpx.Request("GET", url)
    if isinstance(payload, (dict, list)):
        return httpx.Response(status, json=payload, request=request)
    return httpx.Response(status, text=str(payload), request=request)


def test_parse_edeka_web_api_doc_uses_documented_fields():
    valid_to_ms = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp() * 1000)
    row = {
        "angebotid": "A-100",
        "titel": "Bio Äpfel 1 kg",
        "preis": 1.99,
        "beschreibung": "1 kg Schale",
        "basicPrice": "1 kg = 1,99 €",
        "bild_app": "https://offer-images.api.edeka/offer/A-100",
        "gueltig_bis": valid_to_ms,
        "warengruppe": "Obst & Gemüse",
    }
    offer = _parse_edeka_doc(row, _store(), EDEKA_OFFERS_ENDPOINT)
    assert offer is not None
    assert offer.external_offer_id == "A-100"
    assert offer.name == "Bio Äpfel 1 kg"
    assert offer.price == 1.99
    assert offer.quantity_value == 1.0
    assert offer.quantity_unit == "kg"
    assert offer.unit_price == 1.99
    assert offer.image_url == "https://offer-images.api.edeka/offer/A-100"
    assert str(offer.valid_to) == "2026-09-05"
    assert offer.category == "Obst & Gemüse"


def test_edeka_api_fetch_uses_rows_and_start_and_preserves_leading_zero():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _response(200, {"numFound": 1, "start": 0, "docs": [{"angebotid": "1", "titel": "Milch 1 l", "preis": 0.99}]})

    result = _fetch_edeka_api(_store("edeka-071378"), http_get=fake_get)
    assert len(calls) == 1
    assert calls[0][0] == EDEKA_OFFERS_ENDPOINT
    assert calls[0][1]["params"] == {"marketId": "071378", "rows": 100, "start": 0}
    assert result.collector_path == "edeka_web_offer_api"
    assert result.raw_count == 1
    assert result.offers[0].name == "Milch 1 l"
    assert result.artifacts["numFound"] == 1
    assert result.artifacts["pages_fetched"] == 1


def test_edeka_api_fetches_all_pages_when_api_caps_page_size_to_20():
    calls = []
    rows = [{"angebotid": str(i), "titel": f"Artikel {i} 1 kg", "preis": 1.0 + i / 100} for i in range(45)]

    def fake_get(url, **kwargs):
        start = kwargs["params"]["start"]
        calls.append(start)
        page = rows[start:start + 20]
        return _response(200, {"numFound": 45, "start": start, "docs": page})

    result = _fetch_edeka_api(_store(), http_get=fake_get)
    assert calls == [0, 20, 40]
    assert result.raw_count == 45
    assert len(result.offers) == 45
    assert result.artifacts["pages_fetched"] == 3
    assert result.artifacts["numFound"] == 45
    assert [page["received_docs"] for page in result.artifacts["pages"]] == [20, 20, 5]


def test_edeka_api_stops_when_endpoint_repeats_same_page():
    calls = []
    docs = [{"angebotid": str(i), "titel": f"Artikel {i} 1 kg", "preis": 1.0} for i in range(20)]

    def fake_get(url, **kwargs):
        calls.append(kwargs["params"]["start"])
        return _response(200, {"numFound": 200, "docs": docs})

    result = _fetch_edeka_api(_store(), http_get=fake_get)
    assert calls == [0, 20]
    assert result.raw_count == 20
    assert result.artifacts["pages_fetched"] == 2
    assert result.artifacts["pages"][1]["new_docs"] == 0


def test_edeka_api_can_finish_without_numfound_using_empty_page():
    calls = []
    docs = [{"angebotid": str(i), "titel": f"Artikel {i} 1 kg", "preis": 1.0} for i in range(20)]

    def fake_get(url, **kwargs):
        start = kwargs["params"]["start"]
        calls.append(start)
        return _response(200, {"docs": docs if start == 0 else []})

    result = _fetch_edeka_api(_store(), http_get=fake_get)
    assert calls == [0, 20]
    assert result.raw_count == 20


def test_edeka_api_403_fails_closed_with_direct_api_diagnostics():
    def fake_get(url, **kwargs):
        return _response(403, "Access Denied")

    with pytest.raises(WebAuditError) as caught:
        _fetch_edeka_api(_store(), http_get=fake_get)
    assert caught.value.error_type == "blocked"
    assert "HTTP 403" in str(caught.value)
    assert caught.value.artifacts["fetch_mode"] == "edeka-web-api-http"
    assert caught.value.artifacts["http_status"] == 403


def test_edeka_api_requires_verified_numeric_market_id():
    with pytest.raises(WebAuditError) as missing:
        _fetch_edeka_api(_store(None), http_get=lambda *args, **kwargs: None)
    assert missing.value.error_type == "browser_required"

    with pytest.raises(WebAuditError) as invalid:
        _fetch_edeka_api(_store("edeka-unknown"), http_get=lambda *args, **kwargs: None)
    assert invalid.value.error_type == "browser_required"


def test_edeka_api_rejects_changed_response_shape():
    def fake_get(url, **kwargs):
        return _response(200, {"offers": []})

    with pytest.raises(WebAuditError) as caught:
        _fetch_edeka_api(_store(), http_get=fake_get)
    assert caught.value.error_type == "endpoint_changed"
    assert "docs" in str(caught.value)
