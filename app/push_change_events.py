from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .push_service import queue_shared_list_push
from .sharing_models import SharedShoppingListItem

_INFO_KEY = "spareno_push_list_changes"


def _collect(session: Session, list_id: int | None, actor_user_id: int | None, action: str) -> None:
    if list_id is None or actor_user_id is None:
        return
    rows = session.info.setdefault(_INFO_KEY, [])
    rows.append((int(list_id), int(actor_user_id), action))


@event.listens_for(Session, "after_flush")
def _collect_push_changes(session: Session, _flush_context) -> None:
    for row in session.new:
        if isinstance(row, SharedShoppingListItem):
            _collect(session, row.list_id, row.added_by_user_id, "added")

    for row in session.dirty:
        if not isinstance(row, SharedShoppingListItem):
            continue
        checked_history = inspect(row).attrs.checked.history
        if checked_history.has_changes() and bool(row.checked):
            # checked_by_user_id is set by the mutation route, so the actor is unambiguous.
            _collect(session, row.list_id, row.checked_by_user_id, "completed")
        # Re-opening is deliberately silent for now. The model clears checked_by_user_id
        # on reopen, so guessing the actor from added_by would notify the wrong person.


@event.listens_for(Session, "after_commit")
def _queue_push_changes(session: Session) -> None:
    rows = session.info.pop(_INFO_KEY, [])
    grouped: dict[tuple[int, int, str], int] = {}
    for list_id, actor_user_id, action in rows:
        key = (list_id, actor_user_id, action)
        grouped[key] = grouped.get(key, 0) + 1
    for (list_id, actor_user_id, action), count in grouped.items():
        queue_shared_list_push(list_id, actor_user_id, action, count)


@event.listens_for(Session, "after_rollback")
def _drop_push_changes(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
