from datetime import date, datetime, timedelta

import pytest

from app.activity_models import ClientActivityDay, ClientFeatureUsage, ClientUsageSession
from app.client_models import (
    AccountIdentity,
    ClientAppRating,
    ClientDevice,
    ClientPricingFeedback,
    UserClient,
)
from app.db import Base, SessionLocal, engine
from app.lokero_models import FavoriteProductFamily, RegionInterest, ReviewerDeviceGrant
from app.models import UserProfile
from app.user_deletion import RegisteredAccountDeletionBlocked, delete_anonymous_user


def test_delete_anonymous_user_removes_profile_client_and_owned_state():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        user = UserProfile(display_name="Delete Me", postal_code="99999", city="Teststadt")
        db.add(user)
        db.flush()
        client = UserClient(
            client_key="delete_test_client_1234567890",
            user_id=user.id,
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        db.add(client)
        db.flush()
        client_id = client.id
        user_id = user.id

        db.add_all([
            ClientDevice(
                client_id=client_id,
                device_key="delete_test_device_1234567890",
                device_type="desktop",
                os_name="TestOS",
                browser_name="TestBrowser",
            ),
            ClientPricingFeedback(
                client_id=client_id,
                user_id=user_id,
                savings_value="some",
                monthly_price="2.99",
            ),
            ClientAppRating(client_id=client_id, user_id=user_id, rating=4, comment="test"),
            ClientUsageSession(client_id=client_id, page_views=3),
            ClientActivityDay(client_id=client_id, activity_date=date.today(), page_views=2),
            ClientFeatureUsage(client_id=client_id, feature="favorites", use_count=1),
            FavoriteProductFamily(user_id=user_id, family_slug="delete-test-family"),
            RegionInterest(postal_code="99999", email=None, user_id=user_id),
            ReviewerDeviceGrant(
                client_key=client.client_key,
                label="delete-test",
                granted_by="test",
                expires_at=datetime.utcnow() + timedelta(days=1),
            ),
        ])
        db.commit()

        result = delete_anonymous_user(db, user_id)
        assert result is not None
        assert result.user_id == user_id
        assert result.client_count == 1
        db.commit()

        assert db.get(UserProfile, user_id) is None
        assert db.get(UserClient, client_id) is None
        assert db.query(ClientDevice).filter_by(client_id=client_id).count() == 0
        assert db.query(ClientPricingFeedback).filter_by(user_id=user_id).count() == 0
        assert db.query(ClientAppRating).filter_by(user_id=user_id).count() == 0
        assert db.query(ClientUsageSession).filter_by(client_id=client_id).count() == 0
        assert db.query(ClientActivityDay).filter_by(client_id=client_id).count() == 0
        assert db.query(ClientFeatureUsage).filter_by(client_id=client_id).count() == 0
        assert db.query(FavoriteProductFamily).filter_by(user_id=user_id).count() == 0
        assert db.query(RegionInterest).filter_by(user_id=user_id).count() == 0
        assert db.query(ReviewerDeviceGrant).filter_by(client_key="delete_test_client_1234567890").count() == 0
    finally:
        db.close()


def test_delete_anonymous_user_refuses_registered_account():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    user_id = None
    try:
        user = UserProfile(display_name="Registered Test")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(AccountIdentity(
            user_id=user_id,
            provider="supabase",
            provider_subject=f"registered-delete-test-{user_id}",
            email="registered-delete-test@example.test",
        ))
        db.commit()

        with pytest.raises(RegisteredAccountDeletionBlocked):
            delete_anonymous_user(db, user_id)
        db.rollback()

        assert db.get(UserProfile, user_id) is not None
        assert db.query(AccountIdentity).filter_by(user_id=user_id).count() == 1
    finally:
        if user_id is not None:
            db.query(AccountIdentity).filter_by(user_id=user_id).delete()
            db.query(UserProfile).filter_by(id=user_id).delete()
            db.commit()
        db.close()
