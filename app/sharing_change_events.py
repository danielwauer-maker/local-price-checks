from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .list_realtime import publish_list_event
from .sharing_models import SharedShoppingList, SharedShoppingListItem

_INFO_KEY = "spareno_shared_list_events"


def _remember(session: Session, list_id: int | None, revision: int | None = None) -> None:
    if list_id is None:
        return
    rows = session.info.setdefault(_INFO_KEY, {})
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
    for list_id, revision in rows.items():
        publish_list_event(list_id, "revision", revision)


@event.listens_for(Session, "after_rollback")
def _drop_shared_list_changes(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
