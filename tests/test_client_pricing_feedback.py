from fastapi.testclient import TestClient

from app.api_main import app
from app.client_models import ClientPricingFeedback
from app.db import SessionLocal


def test_client_pricing_feedback_is_upserted_once_per_client():
    headers = {"X-LocalPrices-Client": "device_feedback_test_1234567890"}

    with TestClient(app) as client:
        status = client.get("/api/client/feedback", headers=headers)
        assert status.status_code == 200
        assert status.json()["submitted"] is False

        response = client.post(
            "/api/client/feedback",
            headers=headers,
            json={"savingsValue": "some", "monthlyPrice": "2.99"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "submitted": True}

        response = client.post(
            "/api/client/feedback",
            headers=headers,
            json={"savingsValue": "significant", "monthlyPrice": "4.99"},
        )
        assert response.status_code == 200

        status = client.get("/api/client/feedback", headers=headers)
        assert status.status_code == 200
        payload = status.json()
        assert payload["submitted"] is True
        assert payload["savingsValue"] == "significant"
        assert payload["monthlyPrice"] == "4.99"

    db = SessionLocal()
    try:
        rows = db.query(ClientPricingFeedback).all()
        assert len(rows) == 1
        assert rows[0].monthly_price == "4.99"
    finally:
        db.close()


def test_client_pricing_feedback_rejects_unknown_price():
    headers = {"X-LocalPrices-Client": "device_feedback_test_invalid_12345"}
    with TestClient(app) as client:
        response = client.post(
            "/api/client/feedback",
            headers=headers,
            json={"savingsValue": "some", "monthlyPrice": "19.99"},
        )
    assert response.status_code == 422
