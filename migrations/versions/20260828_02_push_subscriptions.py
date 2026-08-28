"""add web push subscriptions

Revision ID: 20260828_02
Revises: 20260828_01
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_02"
down_revision: Union[str, None] = "20260828_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("client_key", sa.String(length=80), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"], unique=False)
    op.create_index("ix_push_subscriptions_client_key", "push_subscriptions", ["client_key"], unique=False)
    op.create_index("ix_push_subscriptions_enabled", "push_subscriptions", ["enabled"], unique=False)
    op.create_index("ix_push_subscriptions_created_at", "push_subscriptions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_created_at", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_enabled", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_client_key", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
