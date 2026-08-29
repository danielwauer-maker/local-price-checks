from __future__ import annotations

from time import perf_counter

from sqlalchemy import event
from sqlalchemy.orm import Session

from .list_realtime import publish_list_event
from .sharing_models import SharedShoppingList, SharedShoppingListItem

_INFO_KEY = "spareno_shared_list_events"
_STARTED_KEY = f"{_INFO_KEY}_started"


def _remember(session: Session, list_id: int | None, revision: int | None = None) -> None:
    if list_id is None:
        return
    rows = session.info.setdefault(_INFO_KEY, {})
    session.info.setdefault(_STARTED_KEY, perf_counter())
    current = rows.get(int(list_id))
    if current is None or (revision is not None and (current is None or revision > current)):
        rows[int(list_id)] = revision


@event.listens_for(Session, "after_flush")
def _collect_shared_list_changes(session: Session, _flush_context) -> None:
    for row in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(row, SharedShoppingList):
            _remember(session, row.id, int(row.revision or 0))
        elif isinstance(row, SharedShoppingListItem):
            _remember(session, row.list_id, None)


@event.listens_for(Session, "after_commit")
def _publish_shared_list_changes(session: Session) -> None:
    rows = session.info.pop(_INFO_KEY, {})
    changed_at = session.info.pop(_STARTED_KEY, None)
    for list_id, revision in rows.items():
        publish_list_event(list_id, "revision", revision, changed_at=changed_at)


@event.listens_for(Session, "after_rollback")
def _drop_shared_list_changes(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
    session.info.pop(_STARTED_KEY, None)
