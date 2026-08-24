from app import account_routes
from app.client_context import reset_client_key, set_client_key
from app.client_models import AccountClientLink, AccountIdentity, UserClient
from app.db import SessionLocal
from app.models import FavoriteStore, UserProfile
from app.supabase_auth import VerifiedSupabaseUser


def test_verified_link_preserves_anonymous_profile(monkeypatch):
    db = SessionLocal()
    user = UserProfile(display_name="Anonymous link test", city="Steimel", radius_km=12)
    db.add(user)
    db.flush()
    client = UserClient(client_key="verified-link-client-0001", user_id=user.id)
    db.add(client)
    db.commit()
    user_id = user.id
    client_id = client.id

    monkeypatch.setattr(
        account_routes,
        "verify_supabase_access_token",
        lambda token: VerifiedSupabaseUser(user_id="supabase-user-1", email="a@example.com"),
    )
    token = set_client_key("verified-link-client-0001")
    try:
        result = account_routes.link_account("Bearer good-token", db)
        assert result["linked"] is True
        assert result["profileId"] == user_id
        assert db.query(AccountIdentity).filter_by(user_id=user_id).count() == 1
        assert db.query(AccountClientLink).filter_by(client_id=client_id).count() == 1
    finally:
        reset_client_key(token)
        db.query(AccountClientLink).filter_by(client_id=client_id).delete()
        db.query(AccountIdentity).filter_by(user_id=user_id).delete()
        db.query(FavoriteStore).filter_by(user_id=user_id).delete()
        db.query(UserClient).filter_by(id=client_id).delete()
        db.query(UserProfile).filter_by(id=user_id).delete()
        db.commit()
        db.close()
