"""reconcile duplicate Lidl Puderbach Store rows

Revision ID: 20260916_01
Revises: 20260910_01
Create Date: 2026-09-16

This is a deliberately narrow, fail-closed data repair for the duplicate that
was created while validating the admin promotion workflow in production.
Store 8 is removed only when Store 16 is provably the canonical promoted row,
the old row is still pre-public, and no business-data foreign keys reference it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260916_01"
down_revision: Union[str, None] = "20260910_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DUPLICATE_STORE_ID = 8
CANONICAL_STORE_ID = 16
EXPECTED_RETAILER = "Lidl"
EXPECTED_POSTAL_CODE = "56305"
_SAFE_WORKFLOW_TABLES = {
    "store_activation_states",
    "store_discovery_candidates",
}


def _normalize(value: str | None) -> str:
    folded = "".join(
        character
        for character in unicodedata.normalize(
            "NFKD", (value or "").casefold().replace("ß", "ss")
        )
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "", folded)


def _addresses_match(left: str | None, right: str | None) -> bool:
    return bool(left and right and _normalize(left) == _normalize(right))


def _store_reference_counts(bind, store_id: int) -> dict[str, int]:
    """Count every direct FK to stores.id so unknown dependencies fail closed."""
    metadata = sa.MetaData()
    metadata.reflect(bind=bind)
    counts: dict[str, int] = {}
    for table in metadata.tables.values():
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
                bind.execute(
                    sa.select(sa.func.count()).select_from(table).where(column == store_id)
                ).scalar_one()
            )
            for column in columns
        )
        if total:
            counts[table.name] = total
    return counts


def _load_store(bind, store_id: int):
    return bind.execute(
        sa.text(
            """
            SELECT id, retailer, postal_code, address, external_id,
                   benchmark_verified, active
            FROM stores
            WHERE id = :store_id
            """
        ),
        {"store_id": store_id},
    ).mappings().first()


def _assert_expected_store(row, *, store_id: int) -> None:
    if row is None:
        raise RuntimeError(f"Expected Store {store_id} is missing")
    if _normalize(row["retailer"]) != _normalize(EXPECTED_RETAILER):
        raise RuntimeError(
            f"Store {store_id} retailer changed: {row['retailer']!r}; refusing repair"
        )
    if str(row["postal_code"] or "") != EXPECTED_POSTAL_CODE:
        raise RuntimeError(
            f"Store {store_id} postcode changed: {row['postal_code']!r}; refusing repair"
        )


def _validate_duplicate_activation_state(bind) -> None:
    row = bind.execute(
        sa.text(
            """
            SELECT lifecycle_status, identity_verified, manually_suspended,
                   last_test_run_id, last_error, published_at, suspended_at
            FROM store_activation_states
            WHERE store_id = :store_id
            """
        ),
        {"store_id": DUPLICATE_STORE_ID},
    ).mappings().first()
    if row is None:
        return

    if row["lifecycle_status"] not in {"discovered", "identity_verified", "promoted"}:
        raise RuntimeError(
            "Duplicate Store 8 has progressed beyond the safe pre-scrape lifecycle: "
            f"{row['lifecycle_status']!r}"
        )
    if row["last_test_run_id"] is not None:
        raise RuntimeError("Duplicate Store 8 already has a test collection run")
    if row["published_at"] is not None:
        raise RuntimeError("Duplicate Store 8 has publication history")
    if row["suspended_at"] is not None or bool(row["manually_suspended"]):
        raise RuntimeError("Duplicate Store 8 has suspension history")
    if (row["last_error"] or "").strip():
        raise RuntimeError("Duplicate Store 8 contains collector error history")


def _validate_physical_identity_evidence(bind, duplicate) -> None:
    rows = bind.execute(
        sa.text(
            """
            SELECT id, matched_store_id, retailer, postal_code, address,
                   source_external_id, status
            FROM store_discovery_candidates
            WHERE postal_code = :postal_code
            """
        ),
        {"postal_code": EXPECTED_POSTAL_CODE},
    ).mappings().all()

    canonical_candidates = [
        row
        for row in rows
        if row["matched_store_id"] == CANONICAL_STORE_ID
        and _normalize(row["retailer"]) == _normalize(EXPECTED_RETAILER)
    ]
    if not canonical_candidates:
        raise RuntimeError(
            "Canonical Store 16 has no explicitly linked Lidl discovery evidence"
        )

    duplicate_external_id = (duplicate["external_id"] or "").strip()
    same_identity = any(
        _addresses_match(duplicate["address"], row["address"])
        or (
            duplicate_external_id
            and (row["source_external_id"] or "").strip() == duplicate_external_id
        )
        for row in canonical_candidates
    )
    if not same_identity:
        raise RuntimeError(
            "Store 8 cannot be proven to represent the same physical Lidl branch as Store 16"
        )

    for row in rows:
        if row["matched_store_id"] != DUPLICATE_STORE_ID:
            continue
        if (
            _normalize(row["retailer"]) != _normalize(EXPECTED_RETAILER)
            or str(row["postal_code"] or "") != EXPECTED_POSTAL_CODE
        ):
            raise RuntimeError(
                f"Candidate {row['id']} linked to Store 8 belongs to a different market"
            )


def upgrade() -> None:
    bind = op.get_bind()
    duplicate = _load_store(bind, DUPLICATE_STORE_ID)
    canonical = _load_store(bind, CANONICAL_STORE_ID)

    # Idempotent no-op if the stale row has already been removed manually.
    if duplicate is None:
        if canonical is not None:
            _assert_expected_store(canonical, store_id=CANONICAL_STORE_ID)
        return

    _assert_expected_store(duplicate, store_id=DUPLICATE_STORE_ID)
    _assert_expected_store(canonical, store_id=CANONICAL_STORE_ID)

    if bool(duplicate["benchmark_verified"]):
        raise RuntimeError("Duplicate Store 8 is public/benchmark-verified; refusing deletion")

    _validate_duplicate_activation_state(bind)
    _validate_physical_identity_evidence(bind, duplicate)

    counts = _store_reference_counts(bind, DUPLICATE_STORE_ID)
    blockers = {
        table_name: count
        for table_name, count in counts.items()
        if table_name not in _SAFE_WORKFLOW_TABLES
    }
    if blockers:
        details = ", ".join(f"{name}={count}" for name, count in sorted(blockers.items()))
        raise RuntimeError(
            "Duplicate Store 8 has business-data dependencies and cannot be removed safely: "
            + details
        )

    # Retain discovery evidence by moving any old explicit links to the canonical
    # promoted Store instead of rejecting the candidates as a false market.
    bind.execute(
        sa.text(
            """
            UPDATE store_discovery_candidates
            SET matched_store_id = :canonical_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE matched_store_id = :duplicate_id
            """
        ),
        {
            "canonical_id": CANONICAL_STORE_ID,
            "duplicate_id": DUPLICATE_STORE_ID,
        },
    )
    bind.execute(
        sa.text("DELETE FROM store_activation_states WHERE store_id = :duplicate_id"),
        {"duplicate_id": DUPLICATE_STORE_ID},
    )
    bind.execute(
        sa.text("DELETE FROM stores WHERE id = :duplicate_id"),
        {"duplicate_id": DUPLICATE_STORE_ID},
    )


def downgrade() -> None:
    # Intentional no-op: the deleted row was a duplicate created by an admin
    # workflow bug. Recreating it would reintroduce the production inconsistency.
    pass
