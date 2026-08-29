from __future__ import annotations

from time import perf_counter

from sqlalchemy import event
from sqlalchemy.orm import Session

from .account_realtime import publish_account_event
from .client_models import AccountAppPreferences, AccountStateRevision
from .lokero_models import FavoriteProductFamily, FavoriteProductPreference
from .models import FavoriteProduct, FavoriteStore, UserProfile

_TRACKED_USER_MODELS = (
    FavoriteProduct,
    FavoriteStore,
    FavoriteProductFamily,
    FavoriteProductPreference,
    AccountAppPreferences,
)
_INFO_KEY = "spareno_account_event_revisions"


def _user_id_for_row(row) -> int | None:
    if isinstance(row, UserProfile):
        return int(row.id) if row.id is not None else None
    if isinstance(row, _TRACKED_USER_MODELS):
        value = getattr(row, "user_id", None)
        return int(value) if value is not None else None
    return None


@event.listens_for(Session, "before_flush")
def _collect_account_changes(session: Session, _flush_context, _instances) -> None:
    revisions = session.info.setdefault(_INFO_KEY, {})
    changed_at = session.info.setdefault(f"{_INFO_KEY}_started", perf_counter())
    user_ids: set[int] = set()
    for row in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(row, UserProfile) and row in session.deleted:
            continue
        user_id = _user_id_for_row(row)
        if user_id is not None and user_id not in revisions:
            user_ids.add(user_id)

    for user_id in user_ids:
        row = (
            session.query(AccountStateRevision)
            .filter(AccountStateRevision.user_id == user_id)
            .with_for_update()
            .first()
        )
        if row is None:
            row = AccountStateRevision(user_id=user_id, revision=1)
            session.add(row)
        else:
            row.revision = int(row.revision or 0) + 1
        revisions[user_id] = {"revision": int(row.revision or 0), "changed_at": changed_at}


@event.listens_for(Session, "after_commit")
def _publish_account_changes(session: Session) -> None:
    revisions = session.info.pop(_INFO_KEY, {})
    session.info.pop(f"{_INFO_KEY}_started", None)
    for user_id, value in revisions.items():
        publish_account_event(
            user_id,
            "state",
            value["revision"],
            changed_at=value["changed_at"],
        )


@event.listens_for(Session, "after_rollback")
def _drop_account_changes(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
    session.info.pop(f"{_INFO_KEY}_started", None)
