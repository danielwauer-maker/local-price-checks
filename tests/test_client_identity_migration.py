from app.client_context import (
    reset_client_key,
    reset_legacy_client_key,
    set_client_key,
    set_legacy_client_key,
)
from app.client_models import UserClient
from app.db import SessionLocal
from app.models import UserProfile
from app.services import current_user


def test_new_device_key_adopts_existing_legacy_client_profile():
    db = SessionLocal()
    profile = UserProfile(display_name="Legacy migration test", radius_km=15)
    db.add(profile)
    db.flush()
    original_user_id = profile.id

    legacy_key = "legacy_client_key_1234567890"
    new_key = "device_new_client_key_1234567890"
    db.add(UserClient(client_key=legacy_key, user_id=original_user_id))
    db.commit()

    client_token = set_client_key(new_key)
    legacy_token = set_legacy_client_key(legacy_key)
    try:
        user = current_user(db)
        assert user.id == original_user_id
        assert db.query(UserClient).filter(UserClient.client_key == legacy_key).count() == 0
        migrated = db.query(UserClient).filter(UserClient.client_key == new_key).one()
        assert migrated.user_id == original_user_id
    finally:
        reset_legacy_client_key(legacy_token)
        reset_client_key(client_token)
        db.query(UserClient).filter(UserClient.user_id == original_user_id).delete()
        db.query(UserProfile).filter(UserProfile.id == original_user_id).delete()
        db.commit()
        db.close()
