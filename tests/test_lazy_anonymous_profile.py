from app.client_context import (
    reset_client_key,
    reset_request_method,
    set_client_key,
    set_request_method,
)
from app.client_models import UserClient
from app.db import SessionLocal
from app.models import UserProfile
from app.services import current_user


def _cleanup(db, client_key: str, user_id: int | None = None) -> None:
    db.query(UserClient).filter(UserClient.client_key == client_key).delete()
    if user_id is not None:
        db.query(UserProfile).filter(UserProfile.id == user_id).delete()
    db.commit()


def test_unknown_get_client_uses_transient_guest_without_database_rows():
    db = SessionLocal()
    client_key = "readonly_guest_client_1234567890"
    before_profiles = db.query(UserProfile).count()
    before_clients = db.query(UserClient).count()

    client_token = set_client_key(client_key)
    method_token = set_request_method("GET")
    try:
        user = current_user(db)
        assert user.id is None
        assert user.display_name == "Gast"
        assert user.radius_km == 15.0
        assert db.query(UserProfile).count() == before_profiles
        assert db.query(UserClient).count() == before_clients
        assert db.query(UserClient).filter(UserClient.client_key == client_key).count() == 0
    finally:
        reset_request_method(method_token)
        reset_client_key(client_token)
        _cleanup(db, client_key)
        db.close()


def test_unknown_personal_write_materializes_profile_and_client():
    db = SessionLocal()
    client_key = "personal_write_client_1234567890"
    client_token = set_client_key(client_key)
    method_token = set_request_method("PUT")
    user_id = None
    try:
        user = current_user(db)
        user_id = user.id
        assert user_id is not None
        assert user.display_name == f"Anonym #{user_id}"
        client = db.query(UserClient).filter(UserClient.client_key == client_key).one()
        assert client.user_id == user_id
    finally:
        reset_request_method(method_token)
        reset_client_key(client_token)
        _cleanup(db, client_key, user_id)
        db.close()


def test_technical_post_can_explicitly_skip_materialization():
    db = SessionLocal()
    client_key = "technical_heartbeat_client_1234567890"
    before_profiles = db.query(UserProfile).count()
    before_clients = db.query(UserClient).count()

    client_token = set_client_key(client_key)
    method_token = set_request_method("POST")
    try:
        user = current_user(db, persist=False)
        assert user.id is None
        assert db.query(UserProfile).count() == before_profiles
        assert db.query(UserClient).count() == before_clients
    finally:
        reset_request_method(method_token)
        reset_client_key(client_token)
        _cleanup(db, client_key)
        db.close()
