from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ListEvent:
    kind: str
    revision: int | None = None


_lock = threading.Lock()
_subscribers: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[ListEvent]]]] = {}


def subscribe_list_events(list_id: int) -> tuple[asyncio.Queue[ListEvent], callable]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[ListEvent] = asyncio.Queue(maxsize=16)
    key = (loop, queue)
    with _lock:
        _subscribers.setdefault(int(list_id), set()).add(key)

    def unsubscribe() -> None:
        with _lock:
            rows = _subscribers.get(int(list_id))
            if rows is None:
                return
            rows.discard(key)
            if not rows:
                _subscribers.pop(int(list_id), None)

    return queue, unsubscribe


def publish_list_event(list_id: int | None, kind: str = "revision", revision: int | None = None) -> None:
    if list_id is None:
        return
    event = ListEvent(kind=kind, revision=revision)
    with _lock:
        targets = list(_subscribers.get(int(list_id), set()))

    for loop, queue in targets:
        def enqueue(q: asyncio.Queue[ListEvent] = queue, e: ListEvent = event) -> None:
            try:
                q.put_nowait(e)
            except asyncio.QueueFull:
                pass

        try:
            loop.call_soon_threadsafe(enqueue)
        except RuntimeError:
            continue
