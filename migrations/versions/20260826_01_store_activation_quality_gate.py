"""add store activation lifecycle and quality assessments

Revision ID: 20260826_01
Revises: 20260825_03
Create Date: 2026-08-26
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_01"
down_revision: Union[str, None] = "20260825_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "store_activation_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False, server_default="promoted"),
        sa.Column("identity_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("manually_suspended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column("last_test_run_id", sa.Integer(), sa.ForeignKey("collection_runs.id"), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("store_id", name="uq_store_activation_state_store"),
    )
    for name, columns in (
        ("ix_store_activation_states_store_id", ["store_id"]),
        ("ix_store_activation_states_lifecycle_status", ["lifecycle_status"]),
        ("ix_store_activation_states_identity_verified", ["identity_verified"]),
        ("ix_store_activation_states_manually_suspended", ["manually_suspended"]),
        ("ix_store_activation_states_last_test_run_id", ["last_test_run_id"]),
        ("ix_store_activation_states_created_at", ["created_at"]),
    ):
        op.create_index(name, "store_activation_states", columns, unique=False)

    op.create_table(
        "store_quality_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("collection_run_id", sa.Integer(), sa.ForeignKey("collection_runs.id"), nullable=False),
        sa.Column(
            "quality_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("collection_quality_snapshots.id"),
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("checks_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("failure_reasons_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("collection_run_id", name="uq_store_quality_assessment_run"),
    )
    for name, columns in (
        ("ix_store_quality_assessments_store_id", ["store_id"]),
        ("ix_store_quality_assessments_collection_run_id", ["collection_run_id"]),
        ("ix_store_quality_assessments_quality_snapshot_id", ["quality_snapshot_id"]),
        ("ix_store_quality_assessments_passed", ["passed"]),
        ("ix_store_quality_assessments_created_at", ["created_at"]),
    ):
        op.create_index(name, "store_quality_assessments", columns, unique=False)

    stores = sa.table(
        "stores",
        sa.column("id", sa.Integer()),
        sa.column("active", sa.Boolean()),
        sa.column("benchmark_verified", sa.Boolean()),
    )
    states = sa.table(
        "store_activation_states",
        sa.column("store_id", sa.Integer()),
        sa.column("lifecycle_status", sa.String()),
        sa.column("identity_verified", sa.Boolean()),
        sa.column("manually_suspended", sa.Boolean()),
        sa.column("published_at", sa.DateTime()),
        sa.column("suspended_at", sa.DateTime()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    now = datetime.utcnow()
    rows = op.get_bind().execute(sa.select(stores.c.id, stores.c.active, stores.c.benchmark_verified)).all()
    if rows:
        op.bulk_insert(
            states,
            [
                {
                    "store_id": row.id,
                    "lifecycle_status": (
                        "public" if row.active and row.benchmark_verified else "suspended" if not row.active else "promoted"
                    ),
                    "identity_verified": bool(row.active and row.benchmark_verified),
                    "manually_suspended": not bool(row.active),
                    "published_at": now if row.active and row.benchmark_verified else None,
                    "suspended_at": now if not row.active else None,
                    "created_at": now,
                    "updated_at": now,
                }
                for row in rows
            ],
        )


def downgrade() -> None:
    op.drop_table("store_quality_assessments")
    op.drop_table("store_activation_states")
