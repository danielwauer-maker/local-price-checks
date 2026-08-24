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


def test_product_families_include_expected_broad_interests():
    client = TestClient(app)
    response = client.get("/api/lokero/product-families")
    assert response.status_code == 200
    payload = response.json()
    slugs = {row["slug"] for row in payload}
    assert {"bier", "cola", "fisch", "kaese"} <= slugs
    for row in payload:
        assert {"slug", "label", "category", "keywords"} <= set(row)


def test_unknown_product_family_cannot_be_favorited():
    client = TestClient(app)
    response = client.put("/api/lokero/favorites/families/definitely-not-a-family")
    assert response.status_code == 404


def test_matched_favorite_offers_endpoint_returns_list():
    client = TestClient(app)
    response = client.get("/api/lokero/favorites/matched-offers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_missing_product_last_offer_returns_null():
    client = TestClient(app)
    response = client.get("/api/lokero/products/999999999/last-offer")
    assert response.status_code == 200
    assert response.json() is None
