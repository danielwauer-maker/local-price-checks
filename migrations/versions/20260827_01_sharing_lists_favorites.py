"""add shared shopping lists and friend favorite sharing

Revision ID: 20260827_01
Revises: 20260826_01
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_01"
down_revision: Union[str, None] = "20260826_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(table: str, specs: tuple[tuple[str, list[str], bool], ...]) -> None:
    for name, columns, unique in specs:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    op.create_table(
        "shared_shopping_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_personal", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _indexes("shared_shopping_lists", (
        ("ix_shared_shopping_lists_owner_user_id", ["owner_user_id"], False),
        ("ix_shared_shopping_lists_is_personal", ["is_personal"], False),
        ("ix_shared_shopping_lists_revision", ["revision"], False),
        ("ix_shared_shopping_lists_created_at", ["created_at"], False),
    ))

    op.create_table(
        "shared_shopping_list_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("list_id", sa.Integer(), sa.ForeignKey("shared_shopping_lists.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("list_id", "user_id", name="uq_shared_list_member"),
    )
    _indexes("shared_shopping_list_members", (
        ("ix_shared_shopping_list_members_list_id", ["list_id"], False),
        ("ix_shared_shopping_list_members_user_id", ["user_id"], False),
        ("ix_shared_shopping_list_members_joined_at", ["joined_at"], False),
    ))

    op.create_table(
        "shared_shopping_list_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("list_id", sa.Integer(), sa.ForeignKey("shared_shopping_lists.id"), nullable=False),
        sa.Column("token", sa.String(length=80), nullable=False),
        sa.Column("invited_email", sa.String(length=320), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=True),
    )
    _indexes("shared_shopping_list_invites", (
        ("ix_shared_shopping_list_invites_list_id", ["list_id"], False),
        ("ix_shared_shopping_list_invites_token", ["token"], True),
        ("ix_shared_shopping_list_invites_invited_email", ["invited_email"], False),
        ("ix_shared_shopping_list_invites_created_by_user_id", ["created_by_user_id"], False),
        ("ix_shared_shopping_list_invites_created_at", ["created_at"], False),
        ("ix_shared_shopping_list_invites_expires_at", ["expires_at"], False),
        ("ix_shared_shopping_list_invites_accepted_by_user_id", ["accepted_by_user_id"], False),
    ))

    op.create_table(
        "shared_shopping_list_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("list_id", sa.Integer(), sa.ForeignKey("shared_shopping_lists.id"), nullable=False),
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=True),
        sa.Column("manual_text", sa.String(length=120), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("added_by_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=True),
        sa.Column("checked_by_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("list_id", "master_product_id", name="uq_shared_list_product"),
    )
    _indexes("shared_shopping_list_items", (
        ("ix_shared_shopping_list_items_list_id", ["list_id"], False),
        ("ix_shared_shopping_list_items_master_product_id", ["master_product_id"], False),
        ("ix_shared_shopping_list_items_checked", ["checked"], False),
        ("ix_shared_shopping_list_items_added_by_user_id", ["added_by_user_id"], False),
        ("ix_shared_shopping_list_items_checked_by_user_id", ["checked_by_user_id"], False),
        ("ix_shared_shopping_list_items_created_at", ["created_at"], False),
    ))

    op.create_table(
        "shared_shopping_list_user_state",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), primary_key=True),
        sa.Column("active_list_id", sa.Integer(), sa.ForeignKey("shared_shopping_lists.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_shared_shopping_list_user_state_active_list_id", "shared_shopping_list_user_state", ["active_list_id"], unique=False)

    op.create_table(
        "favorite_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("token", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _indexes("favorite_shares", (
        ("ix_favorite_shares_owner_user_id", ["owner_user_id"], True),
        ("ix_favorite_shares_token", ["token"], True),
        ("ix_favorite_shares_enabled", ["enabled"], False),
        ("ix_favorite_shares_created_at", ["created_at"], False),
    ))

    op.create_table(
        "favorite_share_item_visibility",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_user_id", "master_product_id", name="uq_favorite_share_item_visibility"),
    )
    _indexes("favorite_share_item_visibility", (
        ("ix_favorite_share_item_visibility_owner_user_id", ["owner_user_id"], False),
        ("ix_favorite_share_item_visibility_master_product_id", ["master_product_id"], False),
        ("ix_favorite_share_item_visibility_visible", ["visible"], False),
    ))

    op.create_table(
        "favorite_share_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscriber_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("share_id", sa.Integer(), sa.ForeignKey("favorite_shares.id"), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("subscriber_user_id", "share_id", name="uq_favorite_share_subscription"),
    )
    _indexes("favorite_share_subscriptions", (
        ("ix_favorite_share_subscriptions_subscriber_user_id", ["subscriber_user_id"], False),
        ("ix_favorite_share_subscriptions_share_id", ["share_id"], False),
        ("ix_favorite_share_subscriptions_created_at", ["created_at"], False),
    ))


def downgrade() -> None:
    op.drop_table("favorite_share_subscriptions")
    op.drop_table("favorite_share_item_visibility")
    op.drop_table("favorite_shares")
    op.drop_table("shared_shopping_list_user_state")
    op.drop_table("shared_shopping_list_items")
    op.drop_table("shared_shopping_list_invites")
    op.drop_table("shared_shopping_list_members")
    op.drop_table("shared_shopping_lists")
