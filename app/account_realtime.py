from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class AccountEvent:
    kind: str = "state"


_lock = threading.Lock()
_subscribers: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[AccountEvent]]]] = {}


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

    def unsubscribe() -> None:
        with _lock:
            rows = _subscribers.get(int(user_id))
            if rows is None:
                return
            rows.discard(key)
            if not rows:
                _subscribers.pop(int(user_id), None)

    return queue, unsubscribe


def publish_account_event(user_id: int | None, kind: str = "state") -> None:
    """Publish a best-effort event from sync or async request handlers."""

    if user_id is None:
        return
    event = AccountEvent(kind=kind)
    with _lock:
        targets = list(_subscribers.get(int(user_id), set()))

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
