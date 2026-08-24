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


def _cleanup_client(db, client_key: str) -> None:
    db.query(UserClient).filter(UserClient.client_key == client_key).delete()
    db.commit()


def test_unknown_get_client_does_not_create_or_claim_database_rows():
    db = SessionLocal()
    client_key = "readonly_guest_client_1234567890"
    before_profiles = db.query(UserProfile).count()
    before_clients = db.query(UserClient).count()

    client_token = set_client_key(client_key)
    method_token = set_request_method("GET")
    try:
        user = current_user(db)
        assert user.radius_km == 15.0 or user.id is not None
        assert db.query(UserProfile).count() == before_profiles
        assert db.query(UserClient).count() == before_clients
        assert db.query(UserClient).filter(UserClient.client_key == client_key).count() == 0
    finally:
        reset_request_method(method_token)
        reset_client_key(client_token)
        _cleanup_client(db, client_key)
        db.close()


def test_unknown_get_can_read_existing_unclaimed_profile_without_claiming_it():
    db = SessionLocal()
    profile = UserProfile(display_name="Read-only seeded profile", radius_km=17)
    db.add(profile)
    db.commit()
    profile_id = profile.id
    client_key = "readonly_seeded_client_1234567890"
    before_clients = db.query(UserClient).count()

    client_token = set_client_key(client_key)
    method_token = set_request_method("GET")
    try:
        user = current_user(db)
        # The oldest unclaimed profile is used for legacy compatibility. The
        # important invariant is that read-only access does not claim/create.
        assert user.id is not None
        assert db.query(UserClient).count() == before_clients
        assert db.query(UserClient).filter(UserClient.client_key == client_key).count() == 0
    finally:
        reset_request_method(method_token)
        reset_client_key(client_token)
        _cleanup_client(db, client_key)
        # Remove only the profile this test created; do not touch any pre-seeded
        # legacy profile that current_user may have returned.
        db.query(UserProfile).filter(UserProfile.id == profile_id).delete()
        db.commit()
        db.close()


def test_unknown_personal_write_materializes_client_and_profile():
    db = SessionLocal()
    client_key = "personal_write_client_1234567890"
    existing_ids = {row[0] for row in db.query(UserProfile.id).all()}
    client_token = set_client_key(client_key)
    method_token = set_request_method("PUT")
    created_user_id = None
    try:
        user = current_user(db)
        assert user.id is not None
        client = db.query(UserClient).filter(UserClient.client_key == client_key).one()
        assert client.user_id == user.id
        if user.id not in existing_ids:
            created_user_id = user.id
            assert user.display_name == f"Anonym #{user.id}"
    finally:
        reset_request_method(method_token)
        reset_client_key(client_token)
        _cleanup_client(db, client_key)
        if created_user_id is not None:
            db.query(UserProfile).filter(UserProfile.id == created_user_id).delete()
            db.commit()
        db.close()


def test_technical_post_can_explicitly_skip_materialization():
    db = SessionLocal()
    client_key = "technical_heartbeat_client_1234567890"
    before_profiles = db.query(UserProfile).count()
    before_clients = db.query(UserClient).count()

    client_token = set_client_key(client_key)
    method_token = set_request_method("POST")
    try:
        current_user(db, persist=False)
        assert db.query(UserProfile).count() == before_profiles
        assert db.query(UserClient).count() == before_clients
        assert db.query(UserClient).filter(UserClient.client_key == client_key).count() == 0
    finally:
        reset_request_method(method_token)
        reset_client_key(client_token)
        _cleanup_client(db, client_key)
        db.close()
