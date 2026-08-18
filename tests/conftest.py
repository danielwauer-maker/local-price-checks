import pytest

from app.client_models import UserClient
from app.db import SessionLocal, engine


@pytest.fixture(autouse=True)
def isolate_user_client_mappings():
    """Keep anonymous browser identities isolated between regression tests.

    Production intentionally persists UserClient rows. The test suite shares one
    database across modules, however, so mappings created by one TestClient must
    not claim seeded profiles for later unrelated tests.
    """
    UserClient.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        db.query(UserClient).delete()
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        db.query(UserClient).delete()
        db.commit()
    finally:
        db.close()
