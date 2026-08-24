import pytest

from app.client_models import ClientAppRating, ClientPricingFeedback, UserClient
from app.db import SessionLocal, engine


@pytest.fixture(autouse=True)
def isolate_user_client_mappings():
    """Keep anonymous browser identities and feedback isolated between tests."""
    UserClient.__table__.create(bind=engine, checkfirst=True)
    ClientPricingFeedback.__table__.create(bind=engine, checkfirst=True)
    ClientAppRating.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        db.query(ClientAppRating).delete()
        db.query(ClientPricingFeedback).delete()
        db.query(UserClient).delete()
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(ClientAppRating).delete()
        db.query(ClientPricingFeedback).delete()
        db.query(UserClient).delete()
        db.commit()
    finally:
        db.close()
