import pytest
from pydantic import ValidationError

from app.client_context import reset_client_key, set_client_key
from app.client_models import ClientAppRating, ClientPricingFeedback, UserClient
from app.client_routes import PricingFeedbackPayload, submit_pricing_feedback
from app.db import SessionLocal
from app.models import UserProfile


def test_rating_feedback_is_persisted_per_client():
    db = SessionLocal()
    profile = UserProfile(display_name="Rating test", radius_km=15)
    db.add(profile)
    db.flush()
    client = UserClient(client_key="rating_test_client_123456789", user_id=profile.id)
    db.add(client)
    db.commit()
    user_id = profile.id
    client_id = client.id

    token = set_client_key(client.client_key)
    try:
        result = submit_pricing_feedback(
            PricingFeedbackPayload(
                savingsValue="some",
                monthlyPrice="4.99",
                rating=4,
                comment="Bitte noch mehr Märkte ergänzen.",
            ),
            db,
        )
        assert result == {"ok": True, "submitted": True}
        pricing = db.query(ClientPricingFeedback).filter_by(client_id=client_id).one()
        rating = db.query(ClientAppRating).filter_by(client_id=client_id).one()
        assert pricing.monthly_price == "4.99"
        assert rating.rating == 4
        assert rating.comment == "Bitte noch mehr Märkte ergänzen."
    finally:
        reset_client_key(token)
        db.query(ClientAppRating).filter_by(client_id=client_id).delete()
        db.query(ClientPricingFeedback).filter_by(client_id=client_id).delete()
        db.query(UserClient).filter_by(id=client_id).delete()
        db.query(UserProfile).filter_by(id=user_id).delete()
        db.commit()
        db.close()


def test_rating_feedback_rejects_invalid_stars_and_long_comments():
    with pytest.raises(ValidationError):
        PricingFeedbackPayload(savingsValue="some", monthlyPrice="2.99", rating=6)
    with pytest.raises(ValidationError):
        PricingFeedbackPayload(savingsValue="some", monthlyPrice="2.99", rating=5, comment="x" * 1001)
