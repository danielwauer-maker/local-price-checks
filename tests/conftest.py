import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

# Test discovery must never inherit the developer's .env database. A fresh,
# process-scoped SQLite database also makes local runs behave like clean CI.
_TEST_DATA_ROOT = Path(tempfile.gettempdir()) / f"spareno-pytest-{uuid4().hex}"
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DATA_ROOT / 'tests.sqlite3'}"
os.environ["DATA_DIR"] = str(_TEST_DATA_ROOT / "data")
os.environ["AUTO_CREATE_SCHEMA"] = "true"

from app.client_models import (
    AccountClientLink,
    AccountIdentity,
    ClientAppRating,
    ClientPricingFeedback,
    UserClient,
)
from app.db import SessionLocal, engine
from app.models import UserProfile


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database():
    yield
    engine.dispose()
    shutil.rmtree(_TEST_DATA_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_user_client_mappings():
    """Keep anonymous browser identities, account links and feedback isolated between tests."""
    UserProfile.__table__.create(bind=engine, checkfirst=True)
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
