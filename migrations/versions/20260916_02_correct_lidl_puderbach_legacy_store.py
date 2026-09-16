"""remove stale Lidl Puderbach legacy identity and keep the official branch

Revision ID: 20260916_02
Revises: 20260916_01
Create Date: 2026-09-16

This deliberately narrow, fail-closed production repair corrects the historic
Lidl identity at Urbacher Straße 31a. The retailer-backed branch is the market
at Urbacherstr. L264 with external ID ``lidl-puderbach-urbacherstr-l264``.

Revision 20260916_01 may already have removed the temporary Store 16 while
resetting its candidates for a manual retest. This follow-up therefore supports
both safe states: it either keeps an existing canonical Store 16 or recreates it
from the exact verified official Lidl candidate after the stale Store 8 has
passed all dependency/publication checks. No business data is moved between
stores. Wrong 31a discovery provenance is retained as rejected audit history.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260916_02"
down_revision: Union[str, None] = "20260916_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_STORE_ID = 8
CANONICAL_STORE_ID = 16
EXPECTED_RETAILER = "Lidl"
EXPECTED_POSTAL_CODE = "56305"
LEGACY_ADDRESS = "Urbacher Straße 31a"
CANONICAL_ADDRESS = "Urbacherstraße L264"
CANONICAL_EXTERNAL_ID = "lidl-puderbach-urbacherstr-l264"
CANONICAL_NAME = "Lidl Puderbach"
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
            SELECT id, name, retailer, postal_code, city, address, latitude,
                   longitude, external_id, source_url, benchmark_verified, active
            FROM stores
            WHERE id = :store_id
            """
        ),
        {"store_id": store_id},
    ).mappings().first()


def _assert_common_store_identity(row, *, store_id: int) -> None:
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


def _assert_legacy_identity(row) -> None:
    _assert_common_store_identity(row, store_id=LEGACY_STORE_ID)
    if _normalize(row["address"]) != _normalize(LEGACY_ADDRESS):
        raise RuntimeError(
            f"Legacy Store {LEGACY_STORE_ID} address changed: {row['address']!r}; refusing repair"
        )
    if bool(row["benchmark_verified"]):
        raise RuntimeError("Legacy Store 8 is public/benchmark-verified; refusing deletion")


def _assert_canonical_identity(row) -> None:
    _assert_common_store_identity(row, store_id=CANONICAL_STORE_ID)
    if _normalize(row["address"]) != _normalize(CANONICAL_ADDRESS):
        raise RuntimeError(
            f"Canonical Store {CANONICAL_STORE_ID} address changed: {row['address']!r}; refusing repair"
        )
    if (row["external_id"] or "").strip() != CANONICAL_EXTERNAL_ID:
        raise RuntimeError(
            f"Canonical Store {CANONICAL_STORE_ID} external ID changed: "
            f"{row['external_id']!r}; refusing repair"
        )


def _validate_legacy_activation_state(bind) -> None:
    row = bind.execute(
        sa.text(
            """
            SELECT lifecycle_status, last_test_run_id, last_error,
                   published_at, suspended_at, manually_suspended
            FROM store_activation_states
            WHERE store_id = :store_id
            """
        ),
        {"store_id": LEGACY_STORE_ID},
    ).mappings().first()
    if row is None:
        return
    if row["lifecycle_status"] not in {"discovered", "identity_verified", "promoted"}:
        raise RuntimeError(
            "Legacy Store 8 progressed beyond the safe pre-scrape lifecycle: "
            f"{row['lifecycle_status']!r}"
        )
    if row["last_test_run_id"] is not None:
        raise RuntimeError("Legacy Store 8 has a test collection run; refusing deletion")
    if row["published_at"] is not None:
        raise RuntimeError("Legacy Store 8 has publication history; refusing deletion")
    if row["suspended_at"] is not None or bool(row["manually_suspended"]):
        raise RuntimeError("Legacy Store 8 has suspension history; refusing deletion")
    if (row["last_error"] or "").strip():
        raise RuntimeError("Legacy Store 8 contains collector error history; refusing deletion")


def _candidate_rows(bind):
    return bind.execute(
        sa.text(
            """
            SELECT id, matched_store_id, retailer, postal_code, name, address,
                   city, latitude, longitude, source, source_external_id,
                   source_url, status, address_verified, coordinates_verified,
                   official_source_verified
            FROM store_discovery_candidates
            WHERE postal_code = :postal_code
              AND retailer = :retailer
            ORDER BY id
            """
        ),
        {"postal_code": EXPECTED_POSTAL_CODE, "retailer": EXPECTED_RETAILER},
    ).mappings().all()


def _canonical_candidate(rows):
    matches = [
        row
        for row in rows
        if str(row["source"] or "").startswith("official:")
        and (row["source_external_id"] or "").strip() == CANONICAL_EXTERNAL_ID
        and _normalize(row["address"]) == _normalize(CANONICAL_ADDRESS)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one official Lidl L264 discovery candidate; "
            f"found {len(matches)}"
        )
    row = matches[0]
    if not (
        bool(row["address_verified"])
        and bool(row["coordinates_verified"])
        and bool(row["official_source_verified"])
    ):
        raise RuntimeError("Official Lidl L264 discovery candidate is not fully verified")
    return row


def _stale_candidates(rows):
    stale = [
        row for row in rows if _normalize(row["address"]) == _normalize(LEGACY_ADDRESS)
    ]
    for row in stale:
        if str(row["source"] or "").startswith("official:"):
            raise RuntimeError(
                f"Candidate {row['id']} claims official Lidl evidence at the stale 31a address; "
                "refusing automatic rejection"
            )
        if row["matched_store_id"] not in {None, LEGACY_STORE_ID, CANONICAL_STORE_ID}:
            raise RuntimeError(
                f"Stale candidate {row['id']} is linked to unexpected Store "
                f"{row['matched_store_id']}; refusing automatic rejection"
            )
    return stale


def _assert_no_unexpected_legacy_candidate_links(rows) -> None:
    stale_ids = {row["id"] for row in _stale_candidates(rows)}
    unexpected = [
        row
        for row in rows
        if row["matched_store_id"] == LEGACY_STORE_ID and row["id"] not in stale_ids
    ]
    if unexpected:
        ids = ", ".join(str(row["id"]) for row in unexpected)
        raise RuntimeError(
            f"Legacy Store 8 is linked to non-31a discovery candidates ({ids}); refusing deletion"
        )


def _reject_stale_candidates(bind, stale) -> None:
    for row in stale:
        bind.execute(
            sa.text(
                """
                UPDATE store_discovery_candidates
                SET matched_store_id = NULL,
                    status = 'rejected',
                    address_verified = 0,
                    coordinates_verified = 0,
                    official_source_verified = 0,
                    verification_note = :note,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :candidate_id
                """
            ),
            {
                "candidate_id": row["id"],
                "note": (
                    "Rejected during verified Lidl Puderbach identity repair: "
                    "official retailer source identifies the branch at Urbacherstr. L264; "
                    "Urbacherstraße 31a is not accepted as Lidl identity evidence."
                ),
            },
        )


def _ensure_canonical_name_is_free(bind) -> None:
    owner = bind.execute(
        sa.text(
            "SELECT id FROM stores WHERE name = :name AND id != :canonical_id LIMIT 1"
        ),
        {"name": CANONICAL_NAME, "canonical_id": CANONICAL_STORE_ID},
    ).scalar_one_or_none()
    if owner is not None:
        raise RuntimeError(
            f"Canonical store name {CANONICAL_NAME!r} is already used by Store {owner}"
        )


def _create_canonical_store_from_candidate(bind, candidate) -> None:
    _ensure_canonical_name_is_free(bind)
    bind.execute(
        sa.text(
            """
            INSERT INTO stores (
                id, retailer, name, postal_code, city, address, latitude,
                longitude, active, benchmark_verified, external_id, source_url
            ) VALUES (
                :id, :retailer, :name, :postal_code, :city, :address, :latitude,
                :longitude, 1, 0, :external_id, :source_url
            )
            """
        ),
        {
            "id": CANONICAL_STORE_ID,
            "retailer": EXPECTED_RETAILER,
            "name": CANONICAL_NAME,
            "postal_code": EXPECTED_POSTAL_CODE,
            "city": candidate["city"],
            "address": CANONICAL_ADDRESS,
            "latitude": candidate["latitude"],
            "longitude": candidate["longitude"],
            "external_id": CANONICAL_EXTERNAL_ID,
            "source_url": candidate["source_url"],
        },
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO store_activation_states (
                store_id, lifecycle_status, identity_verified,
                manually_suspended, created_at, updated_at
            ) VALUES (
                :store_id, 'promoted', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {"store_id": CANONICAL_STORE_ID},
    )


def _link_canonical_candidate(bind, candidate_id: int) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE store_discovery_candidates
            SET matched_store_id = :store_id,
                status = 'promoted',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :candidate_id
            """
        ),
        {"store_id": CANONICAL_STORE_ID, "candidate_id": candidate_id},
    )


def upgrade() -> None:
    bind = op.get_bind()
    legacy = _load_store(bind, LEGACY_STORE_ID)
    canonical = _load_store(bind, CANONICAL_STORE_ID)

    # Fresh/empty installations have no production-specific rows to repair.
    if legacy is None and canonical is None:
        return

    rows = _candidate_rows(bind)
    official = _canonical_candidate(rows)
    stale = _stale_candidates(rows)

    if canonical is not None:
        _assert_canonical_identity(canonical)
        if official["matched_store_id"] not in {None, CANONICAL_STORE_ID}:
            raise RuntimeError(
                "Official Lidl L264 candidate is linked to an unexpected Store: "
                f"{official['matched_store_id']}"
            )

    if legacy is not None:
        _assert_legacy_identity(legacy)
        _validate_legacy_activation_state(bind)
        _assert_no_unexpected_legacy_candidate_links(rows)

        counts = _store_reference_counts(bind, LEGACY_STORE_ID)
        blockers = {
            table_name: count
            for table_name, count in counts.items()
            if table_name not in _SAFE_WORKFLOW_TABLES
        }
        if blockers:
            details = ", ".join(
                f"{name}={count}" for name, count in sorted(blockers.items())
            )
            raise RuntimeError(
                "Legacy Store 8 has business-data dependencies and cannot be deleted safely: "
                + details
            )

    # Keep provenance before deleting either workflow linkage. Rejected rows are
    # excluded from live physical-market grouping by application code.
    _reject_stale_candidates(bind, stale)

    if legacy is not None:
        bind.execute(
            sa.text("DELETE FROM store_activation_states WHERE store_id = :store_id"),
            {"store_id": LEGACY_STORE_ID},
        )
        bind.execute(
            sa.text("DELETE FROM stores WHERE id = :store_id"),
            {"store_id": LEGACY_STORE_ID},
        )

    if canonical is None:
        # 20260916_01 may have removed this pre-public test Store. Recreate only
        # from the exact, fully verified official retailer candidate.
        _create_canonical_store_from_candidate(bind, official)
    else:
        _ensure_canonical_name_is_free(bind)
        bind.execute(
            sa.text("UPDATE stores SET name = :name WHERE id = :store_id"),
            {"name": CANONICAL_NAME, "store_id": CANONICAL_STORE_ID},
        )

    _link_canonical_candidate(bind, official["id"])


def downgrade() -> None:
    # Intentional no-op. Recreating a known-wrong retailer identity would
    # deliberately reintroduce corrupted market data.
    pass
