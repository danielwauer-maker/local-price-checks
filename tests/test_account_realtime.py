import asyncio

from app import account_change_events as _account_change_events  # noqa: F401
from app.account_realtime import publish_account_event, subscribe_account_events
from app.db import SessionLocal
from app.models import UserProfile


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
            finally:
                unsubscribe()

        asyncio.run(run())
    finally:
        db.rollback()
        if profile_id is not None:
            db.query(UserProfile).filter(UserProfile.id == profile_id).delete(synchronize_session=False)
            db.commit()
        db.close()
