from __future__ import annotations

import asyncio
import logging
import threading
from time import perf_counter
from dataclasses import dataclass


@dataclass(frozen=True)
class AccountEvent:
    kind: str = "state"
    revision: int | None = None


_lock = threading.Lock()
_subscribers: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[AccountEvent]]]] = {}
logger = logging.getLogger("spareno.realtime")


def subscribe_account_events(user_id: int) -> tuple[asyncio.Queue[AccountEvent], callable]:
    """Subscribe the current asyncio loop to account-level state changes.

    The hub is intentionally process-local for the current single-backend beta
    deployment. The public SSE contract can later be backed by Redis or
    PostgreSQL LISTEN/NOTIFY without changing the frontend.
    """

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[AccountEvent] = asyncio.Queue(maxsize=8)
    key = (loop, queue)
    with _lock:
        _subscribers.setdefault(int(user_id), set()).add(key)
        active = sum(len(rows) for rows in _subscribers.values())
    logger.info("account_sse_subscribed user_channel=%s active_connections=%s", user_id, active)

    def unsubscribe() -> None:
        with _lock:
            rows = _subscribers.get(int(user_id))
            if rows is None:
                return
            rows.discard(key)
            if not rows:
                _subscribers.pop(int(user_id), None)
            active = sum(len(items) for items in _subscribers.values())
        logger.info("account_sse_unsubscribed user_channel=%s active_connections=%s", user_id, active)

    return queue, unsubscribe


def publish_account_event(
    user_id: int | None,
    kind: str = "state",
    revision: int | None = None,
    *,
    changed_at: float | None = None,
) -> None:
    """Publish a best-effort event from sync or async request handlers."""

    if user_id is None:
        return
    event = AccountEvent(kind=kind, revision=revision)
    with _lock:
        targets = list(_subscribers.get(int(user_id), set()))
    latency_ms = (perf_counter() - changed_at) * 1000 if changed_at is not None else 0.0
    logger.info(
        "account_realtime_published revision=%s subscribers=%s commit_to_publish_ms=%.2f",
        revision,
        len(targets),
        latency_ms,
    )

    for loop, queue in targets:
        def enqueue(q: asyncio.Queue[AccountEvent] = queue, e: AccountEvent = event) -> None:
            try:
                q.put_nowait(e)
            except asyncio.QueueFull:
                # Coalesce bursts: one pending state event is enough to trigger
                # a fresh account-state fetch on the client.
                pass

        try:
            loop.call_soon_threadsafe(enqueue)
        except RuntimeError:
            # Loop already closed; stale subscriber is harmless and will be
            # cleaned up when the stream exits.
            continue
