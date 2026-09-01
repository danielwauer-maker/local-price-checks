from __future__ import annotations

import app.admin_coverage_routes as coverage_routes


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_germany_postcode_geojson_is_loaded_server_side_and_cached(monkeypatch):
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"plz": "57610"},
                "geometry": {"type": "Polygon", "coordinates": []},
            }
        ],
    }
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(payload)

    monkeypatch.setattr(coverage_routes, "_germany_postcode_geojson_cache", None)
    monkeypatch.setattr(coverage_routes.httpx, "get", fake_get)

    assert coverage_routes._load_germany_postcode_geojson() is payload
    assert coverage_routes._load_germany_postcode_geojson() is payload
    assert len(calls) == 1
    assert calls[0][0] == coverage_routes.GERMANY_POSTCODE_GEOJSON_URL
    assert calls[0][1]["follow_redirects"] is True


def test_germany_postcode_geojson_rejects_invalid_payload(monkeypatch):
    monkeypatch.setattr(coverage_routes, "_germany_postcode_geojson_cache", None)
    monkeypatch.setattr(
        coverage_routes.httpx,
        "get",
        lambda *args, **kwargs: _Response({"type": "FeatureCollection", "features": []}),
    )

    try:
        coverage_routes._load_germany_postcode_geojson()
    except ValueError as exc:
        assert "keine Flächen" in str(exc)
    else:
        raise AssertionError("invalid GeoJSON payload should be rejected")
