from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import model_registry  # noqa: F401 - register every direct Store FK
from .coverage_models import StoreDiscoveryCandidate
from .db import Base
from .market_activation import StoreActivationState
from .models import Store


@dataclass(frozen=True)
class StoreDeletePreview:
    allowed: bool
    blockers: tuple[str, ...]
    dependent_counts: dict[str, int]


_SAFE_WORKFLOW_TABLES = {
    "store_activation_states",
    "store_discovery_candidates",
}


def _direct_store_reference_counts(db: Session, store_id: int) -> dict[str, int]:
    """Inspect registered metadata so new business FKs fail closed by default."""
    counts: dict[str, int] = {}
    for table in Base.metadata.tables.values():
        if table.name == "stores":
            continue
        columns = [
            foreign_key.parent
            for foreign_key in table.foreign_keys
            if foreign_key.column.table.name == "stores"
            and foreign_key.column.name == "id"
        ]
        total = sum(
            int(
                db.execute(
                    select(func.count()).select_from(table).where(column == store_id)
                ).scalar_one()
            )
            for column in columns
        )
        if total:
            counts[table.name] = total
    return counts


def preview_false_store_delete(db: Session, store: Store) -> StoreDeletePreview:
    blockers: list[str] = []
    if store.benchmark_verified:
        blockers.append("Markt ist öffentlich/benchmark-verifiziert")

    counts = _direct_store_reference_counts(db, store.id)
    for table_name, count in sorted(counts.items()):
        if table_name not in _SAFE_WORKFLOW_TABLES:
            blockers.append(f"{table_name}: {count} abhängige Datensätze")

    return StoreDeletePreview(
        allowed=not blockers,
        blockers=tuple(blockers),
        dependent_counts=counts,
    )


def delete_false_store(db: Session, store: Store) -> StoreDeletePreview:
    """Delete only one exact pre-public row while retaining discovery evidence."""
    preview = preview_false_store_delete(db, store)
    if not preview.allowed:
        return preview

    now = datetime.utcnow()
    candidates = db.query(StoreDiscoveryCandidate).filter_by(matched_store_id=store.id).all()
    for candidate in candidates:
        candidate.matched_store_id = None
        candidate.status = "rejected"
        marker = f"Store {store.id} als falscher Markt dauerhaft gelöscht"
        candidate.verification_note = (
            f"{candidate.verification_note}; {marker}"
            if candidate.verification_note
            else marker
        )
        candidate.updated_at = now

    db.query(StoreActivationState).filter_by(store_id=store.id).delete(
        synchronize_session=False
    )
    db.delete(store)
    db.flush()
    return preview
