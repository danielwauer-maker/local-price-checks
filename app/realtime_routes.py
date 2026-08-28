from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .db import SessionLocal, get_db
from .list_realtime import subscribe_list_events
from .sharing_models import SharedShoppingList
from .sharing_routes import _member, _require_linked_user, _require_member

router = APIRouter(tags=["realtime"])


@router.get("/api/sharing/lists/{list_id}/events")
async def realtime_list_events(list_id: int, request: Request, db: Session = Depends(get_db)):
    user, _ = _require_linked_user(db)
    shopping_list, _ = _require_member(db, list_id, user.id)
    user_id = int(user.id)
    queue, unsubscribe = subscribe_list_events(list_id)
    initial_revision = int(shopping_list.revision or 0)

    async def stream():
        try:
            yield f"event: ready\ndata: {json.dumps({'revision': initial_revision})}\n\n"
            yield f"event: revision\ndata: {json.dumps({'revision': initial_revision})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    payload = {"revision": event.revision} if event.revision is not None else {}
                    yield f"event: {event.kind}\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    # Revalidate access occasionally without polling list revisions.
                    session = SessionLocal()
                    try:
                        if _member(session, list_id, user_id) is None:
                            yield "event: access_revoked\ndata: {}\n\n"
                            break
                        if session.get(SharedShoppingList, list_id) is None:
                            yield "event: removed\ndata: {}\n\n"
                            break
                    finally:
                        session.close()
                    yield ": keep-alive\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
