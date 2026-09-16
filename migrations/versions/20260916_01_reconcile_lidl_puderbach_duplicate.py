"""roll back accidental duplicate Lidl Puderbach promotion

Revision ID: 20260916_01
Revises: 20260910_01
Create Date: 2026-09-16

This deliberately narrow, fail-closed data repair originally assumed Store 16
was a duplicate of legacy Store 8. Production evidence later proved these rows
represent different physical identities: Store 8 is stale 31a history while
Store 16 is the official L264 branch. Therefore this revision now performs the
old rollback only when same-branch evidence is actually present. Otherwise it
is a safe no-op and lets revision 20260916_02 perform the canonical repair.
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


LEGACY_STORE_ID = 8
ACCIDENTAL_STORE_ID = 16
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


def _validate_accidental_activation_state(bind) -> None:
    row = bind.execute(
        sa.text(
            """
            SELECT lifecycle_status, identity_verified, manually_suspended,
                   last_test_run_id, last_error, published_at, suspended_at
            FROM store_activation_states
            WHERE store_id = :store_id
            """
        ),
        {"store_id": ACCIDENTAL_STORE_ID},
    ).mappings().first()
    if row is None:
        return

    if row["lifecycle_status"] not in {"discovered", "identity_verified", "promoted"}:
        raise RuntimeError(
            "Accidental Store 16 has progressed beyond the safe pre-scrape lifecycle: "
            f"{row['lifecycle_status']!r}"
        )
    if row["last_test_run_id"] is not None:
        raise RuntimeError("Accidental Store 16 already has a test collection run")
    if row["published_at"] is not None:
        raise RuntimeError("Accidental Store 16 has publication history")
    if row["suspended_at"] is not None or bool(row["manually_suspended"]):
        raise RuntimeError("Accidental Store 16 has suspension history")
    if (row["last_error"] or "").strip():
        raise RuntimeError("Accidental Store 16 contains collector error history")


def _same_physical_identity(bind, legacy) -> bool:
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

    accidental_candidates = [
        row
        for row in rows
        if row["matched_store_id"] == ACCIDENTAL_STORE_ID
        and _normalize(row["retailer"]) == _normalize(EXPECTED_RETAILER)
    ]
    if not accidental_candidates:
        return False

    for row in accidental_candidates:
        if (
            _normalize(row["retailer"]) != _normalize(EXPECTED_RETAILER)
            or str(row["postal_code"] or "") != EXPECTED_POSTAL_CODE
        ):
            raise RuntimeError(
                f"Candidate {row['id']} linked to Store 16 belongs to a different market"
            )

    legacy_external_id = (legacy["external_id"] or "").strip()
    return any(
        _addresses_match(legacy["address"], row["address"])
        or (
            legacy_external_id
            and (row["source_external_id"] or "").strip() == legacy_external_id
        )
        for row in accidental_candidates
    )


def upgrade() -> None:
    bind = op.get_bind()
    legacy = _load_store(bind, LEGACY_STORE_ID)
    accidental = _load_store(bind, ACCIDENTAL_STORE_ID)

    # Idempotent no-op if the accidental row has already been removed manually.
    if accidental is None:
        if legacy is not None:
            _assert_expected_store(legacy, store_id=LEGACY_STORE_ID)
        return

    _assert_expected_store(legacy, store_id=LEGACY_STORE_ID)
    _assert_expected_store(accidental, store_id=ACCIDENTAL_STORE_ID)

    # Production evidence proved Store 8 (stale 31a identity) and Store 16
    # (official L264 identity) are distinct. In that case this historical
    # rollback must not remove Store 16; revision 20260916_02 owns the repair.
    if not _same_physical_identity(bind, legacy):
        return

    if bool(accidental["benchmark_verified"]):
        raise RuntimeError(
            "Accidental Store 16 is public/benchmark-verified; refusing rollback"
        )

    _validate_accidental_activation_state(bind)

    counts = _store_reference_counts(bind, ACCIDENTAL_STORE_ID)
    blockers = {
        table_name: count
        for table_name, count in counts.items()
        if table_name not in _SAFE_WORKFLOW_TABLES
    }
    if blockers:
        details = ", ".join(f"{name}={count}" for name, count in sorted(blockers.items()))
        raise RuntimeError(
            "Accidental Store 16 has business-data dependencies and cannot be rolled back safely: "
            + details
        )

    bind.execute(
        sa.text(
            """
            UPDATE store_discovery_candidates
            SET matched_store_id = NULL,
                status = CASE
                    WHEN address_verified = 1
                     AND coordinates_verified = 1
                     AND official_source_verified = 1
                    THEN 'verified'
                    WHEN status = 'promoted' THEN 'discovered'
                    ELSE status
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE matched_store_id = :accidental_id
            """
        ),
        {"accidental_id": ACCIDENTAL_STORE_ID},
    )
    bind.execute(
        sa.text("DELETE FROM store_activation_states WHERE store_id = :accidental_id"),
        {"accidental_id": ACCIDENTAL_STORE_ID},
    )
    bind.execute(
        sa.text("DELETE FROM stores WHERE id = :accidental_id"),
        {"accidental_id": ACCIDENTAL_STORE_ID},
    )


def downgrade() -> None:
    # Intentional no-op: recreating the accidental duplicate would reintroduce
    # the production bug this data repair is meant to unwind.
    pass
