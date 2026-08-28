import asyncio
from collections import Counter

from app.list_realtime import publish_list_event, subscribe_list_events
from app.push_service import _batch_body


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
