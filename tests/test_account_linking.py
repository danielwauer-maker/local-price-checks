from app.account_linking import account_profile_for_client, link_verified_identity
from app.client_models import AccountClientLink, AccountIdentity, UserClient
from app.db import SessionLocal
from app.models import UserProfile


def _client(db, key: str, profile: UserProfile) -> UserClient:
    client = UserClient(client_key=key, user_id=profile.id)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def test_first_verified_identity_keeps_existing_anonymous_profile():
    db = SessionLocal()
    try:
        profile = UserProfile(display_name="Anonymous", city="Dierdorf", radius_km=20)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        client = _client(db, "account-link-first", profile)

        canonical = link_verified_identity(
            db,
            client=client,
            provider="supabase",
            provider_subject="user-123",
            email="test@example.com",
        )

        assert canonical.id == profile.id
        assert canonical.city == "Dierdorf"
        assert canonical.radius_km == 20
        identity = db.query(AccountIdentity).one()
        assert identity.user_id == profile.id
        assert db.query(AccountClientLink).filter_by(client_id=client.id).count() == 1
    finally:
        db.close()


def test_second_device_resolves_existing_canonical_account_profile():
    db = SessionLocal()
    try:
        first_profile = UserProfile(display_name="First", radius_km=15)
        second_profile = UserProfile(display_name="Second", radius_km=10)
        db.add_all([first_profile, second_profile])
        db.commit()
        db.refresh(first_profile)
        db.refresh(second_profile)
        first_client = _client(db, "account-link-device-1", first_profile)
        second_client = _client(db, "account-link-device-2", second_profile)

        first_canonical = link_verified_identity(
            db,
            client=first_client,
            provider="supabase",
            provider_subject="user-456",
            email="same@example.com",
        )
        second_canonical = link_verified_identity(
            db,
            client=second_client,
            provider="supabase",
            provider_subject="user-456",
            email="same@example.com",
        )

        assert first_canonical.id == first_profile.id
        assert second_canonical.id == first_profile.id
        assert account_profile_for_client(db, second_client).id == first_profile.id
        assert db.query(AccountClientLink).count() == 2
    finally:
        db.close()
