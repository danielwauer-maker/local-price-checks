"""add account-scoped app preferences

Revision ID: 20260828_01
Revises: 20260827_01
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_01"
down_revision: Union[str, None] = "20260827_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_app_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("travel_cost_per_km", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("notifications_json", sa.Text(), nullable=False, server_default='{"priceAlerts":true,"newOffers":true,"regionAvailable":true,"favoriteOffers":false}'),
        sa.Column("preferred_chains_json", sa.Text(), nullable=False, server_default='["REWE","Lidl","ALDI SÜD","Netto","EDEKA"]'),
        sa.Column("diet_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_account_app_preferences_user"),
    )
    op.create_index("ix_account_app_preferences_user_id", "account_app_preferences", ["user_id"], unique=False)
    op.create_index("ix_account_app_preferences_updated_at", "account_app_preferences", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_account_app_preferences_updated_at", table_name="account_app_preferences")
    op.drop_index("ix_account_app_preferences_user_id", table_name="account_app_preferences")
    op.drop_table("account_app_preferences")
