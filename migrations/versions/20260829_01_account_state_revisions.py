"""add account state revisions

Revision ID: 20260829_01
Revises: 20260828_02
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_01"
down_revision: Union[str, None] = "20260828_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_state_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_account_state_revisions_user_id", "account_state_revisions", ["user_id"], unique=True)
    op.create_index("ix_account_state_revisions_updated_at", "account_state_revisions", ["updated_at"], unique=False)
    op.execute(
        sa.text(
            "INSERT INTO account_state_revisions (user_id, revision, updated_at) "
            "SELECT id, 1, CURRENT_TIMESTAMP FROM user_profiles"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_account_state_revisions_updated_at", table_name="account_state_revisions")
    op.drop_index("ix_account_state_revisions_user_id", table_name="account_state_revisions")
    op.drop_table("account_state_revisions")
