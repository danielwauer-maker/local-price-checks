from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .coverage_models import StoreDiscoveryCandidate
from .db import Base
from .market_activation import StoreActivationState
from .models import Store


@dataclass(frozen=True)
class StoreDeletePreview:
    allowed: bool
    blockers: tuple[str, ...]
    dependent_counts: dict[str, int]


# These references are workflow metadata and can be safely detached/deleted when
# an admin explicitly confirms that a pre-public Store row represents a false
# market. All business/user/history references block hard deletion.
_SAFE_WORKFLOW_TABLES = {
    "store_activation_states",
    "store_discovery_candidates",
}


def _direct_store_reference_counts(db: Session, store_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in Base.metadata.tables.values():
        if table.name == "stores":
            continue
        store_fk_columns = [
            fk.parent
            for fk in table.foreign_keys
            if fk.column.table.name == "stores" and fk.column.name == "id"
        ]
        if not store_fk_columns:
            continue
        total = 0
        for column in store_fk_columns:
            total += int(
                db.execute(
                    select(func.count()).select_from(table).where(column == store_id)
                ).scalar_one()
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
        if table_name in _SAFE_WORKFLOW_TABLES:
            continue
        blockers.append(f"{table_name}: {count} abhängige Datensätze")

    return StoreDeletePreview(
        allowed=not blockers,
        blockers=tuple(blockers),
        dependent_counts=counts,
    )


def delete_false_store(db: Session, store: Store) -> StoreDeletePreview:
    """Hard-delete one explicitly false pre-public Store row with guardrails.

    Candidates that produced the false Store are *rejected*, not deleted. Their
    provider provenance therefore remains visible and the same discovery key
    cannot silently promote the bad market again on the next postcode refresh.
    """
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
            f"{candidate.verification_note}; {marker}" if candidate.verification_note else marker
        )
        candidate.updated_at = now

    db.query(StoreActivationState).filter_by(store_id=store.id).delete(synchronize_session=False)
    db.delete(store)
    db.flush()
    return preview
