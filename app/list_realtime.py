from __future__ import annotations

import asyncio
import logging
import threading
from time import perf_counter
from dataclasses import dataclass


@dataclass(frozen=True)
class ListEvent:
    kind: str
    revision: int | None = None


_lock = threading.Lock()
_subscribers: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[ListEvent]]]] = {}
logger = logging.getLogger("spareno.realtime")


def subscribe_list_events(list_id: int) -> tuple[asyncio.Queue[ListEvent], callable]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[ListEvent] = asyncio.Queue(maxsize=16)
    key = (loop, queue)
    with _lock:
        _subscribers.setdefault(int(list_id), set()).add(key)
        active = sum(len(rows) for rows in _subscribers.values())
    logger.info("list_sse_subscribed list_channel=%s active_connections=%s", list_id, active)

    def unsubscribe() -> None:
        with _lock:
            rows = _subscribers.get(int(list_id))
            if rows is None:
                return
            rows.discard(key)
            if not rows:
                _subscribers.pop(int(list_id), None)
            active = sum(len(items) for items in _subscribers.values())
        logger.info("list_sse_unsubscribed list_channel=%s active_connections=%s", list_id, active)

    return queue, unsubscribe


def publish_list_event(
    list_id: int | None,
    kind: str = "revision",
    revision: int | None = None,
    *,
    changed_at: float | None = None,
) -> None:
    if list_id is None:
        return
    event = ListEvent(kind=kind, revision=revision)
    with _lock:
        targets = list(_subscribers.get(int(list_id), set()))
    latency_ms = (perf_counter() - changed_at) * 1000 if changed_at is not None else 0.0
    logger.info(
        "list_realtime_published list_channel=%s revision=%s subscribers=%s commit_to_publish_ms=%.2f",
        list_id,
        revision,
        len(targets),
        latency_ms,
    )

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
