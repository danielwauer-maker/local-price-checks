"""repair stale ALDI SÜD Altenkirchen Store source provenance

Revision ID: 20260918_01
Revises: 20260916_02
Create Date: 2026-09-18

PR #257 replaced the obsolete Scene7 environmental PDF with the official ALDI
branch page for discovery provenance and separated identity provenance from the
regional offer collector. Store 17 had already been promoted before that fix,
so its persisted ``stores.source_url`` was intentionally left untouched.

This migration repairs only that known stale metadata value. It is deliberately
fail-closed: exactly one ALDI SÜD Store at Kölner Straße 30a / 57610
Altenkirchen must exist and its current source must be either the known obsolete
PDF or the already-correct target URL. No Store identity, coordinates, external
ID, publication state, offer data or collection history is changed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260918_01"
down_revision: Union[str, None] = "20260916_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXPECTED_RETAILER = "ALDI SÜD"
EXPECTED_POSTAL_CODE = "57610"
EXPECTED_CITY = "Altenkirchen"
EXPECTED_ADDRESS = "Kölner Straße 30a"
STALE_SOURCE_URL = (
    "https://s7g10.scene7.com/is/content/aldi/"
    "ALDI_SUED_Umwelterklaerung-2024.pdf"
)
TARGET_SOURCE_URL = (
    "https://filialen.aldi-sued.de/rheinland-pfalz/altenkirchen/"
    "koelner-strasse-30a"
)


def _normalize(value: str | None) -> str:
    folded = "".join(
        character
        for character in unicodedata.normalize(
            "NFKD", (value or "").casefold().replace("ß", "ss")
        )
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "", folded)


def _matching_store(bind):
    rows = bind.execute(
        sa.text(
            """
            SELECT id, retailer, name, postal_code, city, address, source_url,
                   external_id, active, benchmark_verified
            FROM stores
            WHERE postal_code = :postal_code
            """
        ),
        {"postal_code": EXPECTED_POSTAL_CODE},
    ).mappings().all()
    matches = [
        row
        for row in rows
        if _normalize(row["retailer"]) == _normalize(EXPECTED_RETAILER)
        and _normalize(row["city"]) == _normalize(EXPECTED_CITY)
        and _normalize(row["address"]) == _normalize(EXPECTED_ADDRESS)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one ALDI SÜD Altenkirchen Store at Kölner Straße 30a; "
            f"found {len(matches)}"
        )
    return matches[0]


def _repair_source(bind) -> bool:
    row = _matching_store(bind)
    current = (row["source_url"] or "").strip()
    if current == TARGET_SOURCE_URL:
        return False
    if current != STALE_SOURCE_URL:
        raise RuntimeError(
            "ALDI SÜD Altenkirchen source changed unexpectedly; refusing automatic "
            f"overwrite for Store {row['id']}: {current!r}"
        )

    result = bind.execute(
        sa.text(
            """
            UPDATE stores
            SET source_url = :target
            WHERE id = :store_id AND source_url = :stale
            """
        ),
        {
            "target": TARGET_SOURCE_URL,
            "store_id": row["id"],
            "stale": STALE_SOURCE_URL,
        },
    )
    if result.rowcount not in {-1, 1}:
        raise RuntimeError(
            "Unexpected ALDI SÜD Altenkirchen source repair row count: "
            f"{result.rowcount}"
        )
    return True


def upgrade() -> None:
    _repair_source(op.get_bind())


def downgrade() -> None:
    # This is a metadata correction. Restoring the known-broken environmental
    # PDF would knowingly reintroduce invalid Store provenance, so downgrade is
    # intentionally a no-op.
    pass
