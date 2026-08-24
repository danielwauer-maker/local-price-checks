from app.main import app


def test_lokero_categories_endpoint(client):
    response = client.get('/api/lokero/categories')
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    if payload:
        assert {'id', 'label', 'count'} <= set(payload[0])


def test_lokero_product_media_missing_returns_404(client):
    response = client.get('/api/lokero/product-media/999999999')
    assert response.status_code == 404
