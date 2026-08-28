from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from .account_realtime import publish_account_event
from .client_models import AccountAppPreferences
from .lokero_models import FavoriteProductFamily, FavoriteProductPreference
from .models import FavoriteProduct, FavoriteStore, UserProfile

_TRACKED_USER_MODELS = (
    FavoriteProduct,
    FavoriteStore,
    FavoriteProductFamily,
    FavoriteProductPreference,
    AccountAppPreferences,
)
_INFO_KEY = "spareno_account_event_user_ids"


def _user_id_for_row(row) -> int | None:
    if isinstance(row, UserProfile):
        return int(row.id) if row.id is not None else None
    if isinstance(row, _TRACKED_USER_MODELS):
        value = getattr(row, "user_id", None)
        return int(value) if value is not None else None
    return None


@event.listens_for(Session, "after_flush")
def _collect_account_changes(session: Session, _flush_context) -> None:
    user_ids = session.info.setdefault(_INFO_KEY, set())
    for row in list(session.new) + list(session.dirty) + list(session.deleted):
        user_id = _user_id_for_row(row)
        if user_id is not None:
            user_ids.add(user_id)


@event.listens_for(Session, "after_commit")
def _publish_account_changes(session: Session) -> None:
    user_ids = session.info.pop(_INFO_KEY, set())
    for user_id in user_ids:
        publish_account_event(user_id, "state")


@event.listens_for(Session, "after_rollback")
def _drop_account_changes(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
