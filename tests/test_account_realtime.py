import asyncio
from datetime import datetime

from app import account_change_events as _account_change_events  # noqa: F401
from app.account_linking import account_profile_for_client
from app.account_realtime import publish_account_event, subscribe_account_events
from app.client_context import (
    reset_client_key,
    reset_legacy_client_key,
    reset_request_method,
    set_client_key,
    set_legacy_client_key,
    set_request_method,
)
from app.client_models import AccountClientLink, AccountIdentity, UserClient
from app.db import SessionLocal
from app.models import UserProfile
from app.services import current_user


def test_account_event_hub_delivers_state_event():
    async def run():
        queue, unsubscribe = subscribe_account_events(987654)
        try:
            publish_account_event(987654, "favorites")
            event = await asyncio.wait_for(queue.get(), timeout=1)
            assert event.kind == "favorites"
        finally:
            unsubscribe()

    asyncio.run(run())


def test_profile_commit_publishes_account_state_event():
    db = SessionLocal()
    profile_id = None
    try:
        profile = UserProfile(display_name="Realtime test", radius_km=15)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        profile_id = profile.id

        async def run():
            queue, unsubscribe = subscribe_account_events(profile.id)
            try:
                profile.city = "Puderbach"
                db.commit()
                event = await asyncio.wait_for(queue.get(), timeout=1)
                assert event.kind == "state"
                assert event.revision == 1
                await asyncio.sleep(0.05)
                assert queue.empty()
            finally:
                unsubscribe()

        asyncio.run(run())
    finally:
        db.rollback()
        if profile_id is not None:
            db.query(UserProfile).filter(UserProfile.id == profile_id).delete(synchronize_session=False)
            db.commit()
        db.close()


def test_account_get_and_sse_identity_resolution_remain_read_only():
    db = SessionLocal()
    profile_id = None
    shadow_id = None
    client_token = legacy_token = method_token = None
    try:
        canonical = UserProfile(display_name="Read only canonical")
        shadow = UserProfile(display_name="Read only shadow")
        db.add_all([canonical, shadow])
        db.flush()
        profile_id, shadow_id = canonical.id, shadow.id
        fixed = datetime(2024, 1, 2, 3, 4, 5)
        legacy = UserClient(
            client_key="read-only-legacy-client",
            user_id=shadow.id,
            first_seen_at=fixed,
            last_seen_at=fixed,
        )
        db.add(legacy)
        db.flush()
        identity = AccountIdentity(
            user_id=canonical.id,
            provider="test",
            provider_subject="read-only",
            last_seen_at=fixed,
        )
        db.add(identity)
        db.flush()
        link = AccountClientLink(identity_id=identity.id, client_id=legacy.id, linked_at=fixed, last_seen_at=fixed)
        db.add(link)
        db.commit()

        assert account_profile_for_client(db, legacy).id == canonical.id
        assert not db.new and not db.dirty and not db.deleted

        client_token = set_client_key("read-only-new-client")
        legacy_token = set_legacy_client_key("read-only-legacy-client")
        method_token = set_request_method("GET")
        for _ in range(25):
            assert current_user(db).id == canonical.id
            assert not db.new and not db.dirty and not db.deleted

        db.refresh(legacy)
        db.refresh(identity)
        db.refresh(link)
        assert legacy.client_key == "read-only-legacy-client"
        assert legacy.last_seen_at == fixed
        assert identity.last_seen_at == fixed
        assert link.last_seen_at == fixed
    finally:
        if method_token is not None:
            reset_request_method(method_token)
        if legacy_token is not None:
            reset_legacy_client_key(legacy_token)
        if client_token is not None:
            reset_client_key(client_token)
        db.rollback()
        if profile_id is not None:
            db.query(AccountClientLink).delete(synchronize_session=False)
            db.query(AccountIdentity).filter(AccountIdentity.provider_subject == "read-only").delete(synchronize_session=False)
            db.query(UserClient).filter(UserClient.client_key == "read-only-legacy-client").delete(synchronize_session=False)
            db.query(UserProfile).filter(UserProfile.id.in_([profile_id, shadow_id])).delete(synchronize_session=False)
            db.commit()
        db.close()
