import asyncio
from collections import Counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.admin_routes import _admin
from app.api_main import app
from app.db import Base, SessionLocal, engine
from app.list_realtime import publish_list_event, subscribe_list_events
from app.models import AdminAuditLog, UserProfile
from app.push_models import PushSubscription
from app.push_routes import _safe_internal_target, _trusted_push_endpoint
from app.push_service import _BATCHES, _BATCH_LOCK, _batch_body, queue_shared_list_push
from app.sharing_models import SharedShoppingList, SharedShoppingListMember


def test_list_realtime_hub_delivers_revision():
    async def run():
        queue, unsubscribe = subscribe_list_events(987654)
        try:
            publish_list_event(987654, "revision", 42)
            event = await asyncio.wait_for(queue.get(), timeout=1)
            assert event.kind == "revision"
            assert event.revision == 42
        finally:
            unsubscribe()

    asyncio.run(run())


def test_shopping_push_aggregates_multiple_actions():
    title, body = _batch_body("Familienliste", Counter({"added": 2, "completed": 3}))
    assert title == "Familienliste wurde aktualisiert"
    assert "2 Artikel wurden hinzugefügt" in body
    assert "3 Artikel wurden erledigt" in body


def test_shopping_push_uses_singular_wording():
    _, body = _batch_body("Einkauf", Counter({"completed": 1}))
    assert body == "1 Artikel wurde erledigt"


def test_push_endpoint_accepts_known_browser_push_services():
    assert _trusted_push_endpoint("https://fcm.googleapis.com/fcm/send/example")
    assert _trusted_push_endpoint("https://updates.push.services.mozilla.com/wpush/v2/example")
    assert _trusted_push_endpoint("https://web.push.apple.com/Q/example")


def test_push_endpoint_rejects_untrusted_or_non_https_targets():
    assert not _trusted_push_endpoint("http://fcm.googleapis.com/fcm/send/example")
    assert not _trusted_push_endpoint("https://127.0.0.1/push")
    assert not _trusted_push_endpoint("https://example.test/push")
    assert not _trusted_push_endpoint("https://web.push.apple.com:8443/Q/example")


def test_admin_push_target_accepts_only_internal_spareno_paths():
    assert _safe_internal_target("/liste")
    assert _safe_internal_target("/produkt/42?from=push")
    assert not _safe_internal_target("https://example.test/liste")
    assert not _safe_internal_target("//example.test/liste")
    assert not _safe_internal_target("/liste/../admin")
    assert not _safe_internal_target("/liste/%252e%252e/admin")
    assert not _safe_internal_target("/liste#external")


@pytest.fixture
def admin_client():
    app.dependency_overrides[_admin] = lambda: "push-test-admin"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(_admin, None)


def _push_user_with_devices() -> tuple[int, int, int, int]:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        user = UserProfile(display_name="Custom push target")
        other = UserProfile(display_name="Other push target")
        db.add_all([user, other])
        db.flush()
        suffix = uuid4().hex
        devices = [
            PushSubscription(user_id=user.id, client_key=f"push-device-a-{suffix}", endpoint=f"https://fcm.googleapis.com/fcm/send/a-{suffix}", p256dh="a", auth="a"),
            PushSubscription(user_id=user.id, client_key=f"push-device-b-{suffix}", endpoint=f"https://fcm.googleapis.com/fcm/send/b-{suffix}", p256dh="b", auth="b"),
            PushSubscription(user_id=other.id, client_key=f"push-device-other-{suffix}", endpoint=f"https://fcm.googleapis.com/fcm/send/c-{suffix}", p256dh="c", auth="c"),
        ]
        db.add_all(devices)
        db.commit()
        return user.id, other.id, devices[0].id, devices[2].id
    finally:
        db.close()


def test_admin_custom_push_all_devices_specific_device_result_and_audit(admin_client, monkeypatch):
    user_id, _, own_device_id, _ = _push_user_with_devices()
    calls = []

    def fake_send(_db, sent_user_id, **kwargs):
        calls.append((sent_user_id, kwargs))
        return 1 if kwargs["subscription_id"] is not None else 2

    monkeypatch.setattr("app.push_routes.send_push_to_user", fake_send)
    headers = {"origin": "http://testserver"}
    response = admin_client.post(
        f"/admin/users/{user_id}/push-custom",
        data={"title": "Beta bereit", "body": "Jetzt Einkaufsliste prüfen", "target": "/liste?from=push", "subscription_id": ""},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith(f"push_user={user_id}&push_sent=2&push_failed=0&custom_push=1")
    assert calls[-1] == (user_id, {
        "title": "Beta bereit",
        "body": "Jetzt Einkaufsliste prüfen",
        "url": "/liste?from=push",
        "tag": f"admin-custom-{user_id}",
        "data": {"type": "admin_custom"},
        "subscription_id": None,
    })

    response = admin_client.post(
        f"/admin/users/{user_id}/push-custom",
        data={"title": "Gerät", "body": "Nur dieses Gerät", "target": "/favoriten", "subscription_id": str(own_device_id)},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert f"push_sent=1&push_failed=0" in response.headers["location"]
    assert calls[-1][1]["subscription_id"] == own_device_id

    db = SessionLocal()
    try:
        rows = db.query(AdminAuditLog).filter(
            AdminAuditLog.action == "admin_custom_push",
            AdminAuditLog.entity_id == str(user_id),
        ).order_by(AdminAuditLog.id.desc()).limit(2).all()
        assert len(rows) == 2
        assert all(row.actor == "push-test-admin" for row in rows)
        assert "target=/favoriten" in rows[0].details
        assert "Nur dieses Gerät" not in rows[0].details
        assert "Gerät" not in rows[0].details
    finally:
        db.close()


def test_admin_custom_push_rejects_external_target_foreign_device_and_cross_origin(admin_client, monkeypatch):
    user_id, _, _, foreign_device_id = _push_user_with_devices()
    monkeypatch.setattr("app.push_routes.send_push_to_user", lambda *_args, **_kwargs: 0)
    valid = {"title": "Titel", "body": "Nachricht", "target": "/liste", "subscription_id": ""}
    external = admin_client.post(
        f"/admin/users/{user_id}/push-custom",
        data={**valid, "target": "https://example.test/phishing"},
        headers={"origin": "http://testserver"},
    )
    assert external.status_code == 400
    foreign = admin_client.post(
        f"/admin/users/{user_id}/push-custom",
        data={**valid, "subscription_id": str(foreign_device_id)},
        headers={"origin": "http://testserver"},
    )
    assert foreign.status_code == 404
    cross_origin = admin_client.post(
        f"/admin/users/{user_id}/push-custom",
        data=valid,
        headers={"origin": "https://evil.example"},
    )
    assert cross_origin.status_code == 403


def test_shared_list_mutation_queues_push_transport_in_background(monkeypatch):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        owner = UserProfile(display_name="Push queue owner")
        member = UserProfile(display_name="Push queue member")
        db.add_all([owner, member])
        db.flush()
        shopping_list = SharedShoppingList(owner_user_id=owner.id, name="Async push list", is_personal=False)
        db.add(shopping_list)
        db.flush()
        db.add_all([
            SharedShoppingListMember(list_id=shopping_list.id, user_id=owner.id, role="owner"),
            SharedShoppingListMember(list_id=shopping_list.id, user_id=member.id, role="editor"),
        ])
        db.commit()
        list_id, owner_id, member_id = shopping_list.id, owner.id, member.id
    finally:
        db.close()

    started = []

    class DeferredTimer:
        daemon = False

        def __init__(self, _seconds, callback, args=()):
            self.callback = callback
            self.args = args

        def start(self):
            started.append((self.callback, self.args))

    monkeypatch.setattr("app.push_service.threading.Timer", DeferredTimer)
    queue_shared_list_push(list_id, owner_id, "added")
    assert len(started) == 1
    assert started[0][1] == ((list_id, member_id),)
    with _BATCH_LOCK:
        _BATCHES.pop((list_id, member_id), None)
