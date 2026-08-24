import pytest

from app.client_models import (
    AccountClientLink,
    AccountIdentity,
    ClientAppRating,
    ClientPricingFeedback,
    UserClient,
)
from app.db import SessionLocal, engine


@pytest.fixture(autouse=True)
def isolate_user_client_mappings():
    """Keep anonymous browser identities, account links and feedback isolated between tests."""
    UserClient.__table__.create(bind=engine, checkfirst=True)
    AccountIdentity.__table__.create(bind=engine, checkfirst=True)
    AccountClientLink.__table__.create(bind=engine, checkfirst=True)
    ClientPricingFeedback.__table__.create(bind=engine, checkfirst=True)
    ClientAppRating.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        db.query(AccountClientLink).delete()
        db.query(AccountIdentity).delete()
        db.query(ClientAppRating).delete()
        db.query(ClientPricingFeedback).delete()
        db.query(UserClient).delete()
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(AccountClientLink).delete()
        db.query(AccountIdentity).delete()
        db.query(ClientAppRating).delete()
        db.query(ClientPricingFeedback).delete()
        db.query(UserClient).delete()
        db.commit()
    finally:
        db.close()
