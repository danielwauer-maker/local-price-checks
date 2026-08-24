from fastapi.testclient import TestClient

from app.api_main import app


def test_lokero_categories_endpoint():
    client = TestClient(app)
    response = client.get("/api/lokero/categories")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    if payload:
        assert {"id", "label", "icon", "count"} <= set(payload[0])


def test_lokero_product_media_missing_returns_404():
    client = TestClient(app)
    response = client.get("/api/lokero/product-media/999999999")
    assert response.status_code == 404


def test_lokero_media_coverage_endpoint_has_consistent_counts():
    client = TestClient(app)
    response = client.get("/api/lokero/media-coverage")
    assert response.status_code == 200
    payload = response.json()
    assert {
        "currentPublicProducts",
        "withPublicMedia",
        "missingPublicMedia",
        "coveragePercentage",
        "missingProductIds",
    } <= set(payload)
    assert payload["currentPublicProducts"] == payload["withPublicMedia"] + payload["missingPublicMedia"]
    assert 0 <= payload["coveragePercentage"] <= 100
    assert isinstance(payload["missingProductIds"], list)
