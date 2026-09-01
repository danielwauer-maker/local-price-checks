"""add isolated retailer web offer audit snapshots

Revision ID: 20260901_01
Revises: 20260829_01
Create Date: 2026-09-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_01"
down_revision: Union[str, None] = "20260829_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_offer_audit_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("period_key", sa.String(40), nullable=False, server_default="current"),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("collector_path", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="running"),
        sa.Column("error_type", sa.String(60), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_price_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_package_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column("comparison_json", sa.Text(), nullable=True),
    )
    for column in ("store_id", "retailer", "period_key", "status", "error_type", "started_at"):
        op.create_index(f"ix_web_offer_audit_runs_{column}", "web_offer_audit_runs", [column])

    op.create_table(
        "web_offer_audit_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("web_offer_audit_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="web"),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("external_offer_id", sa.String(180), nullable=True),
        sa.Column("external_product_id", sa.String(180), nullable=True),
        sa.Column("ean", sa.String(32), nullable=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("brand", sa.String(180), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("old_price", sa.Float(), nullable=True),
        sa.Column("discount_text", sa.String(160), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("quantity", sa.String(160), nullable=True),
        sa.Column("quantity_value", sa.Float(), nullable=True),
        sa.Column("quantity_unit", sa.String(40), nullable=True),
        sa.Column("packaging_text", sa.String(200), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("category", sa.String(160), nullable=True),
        sa.Column("source_category", sa.String(200), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("image_source", sa.String(80), nullable=True),
        sa.Column("image_alt", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("validation_errors", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(420), nullable=False),
    )
    for column in ("run_id", "store_id", "retailer", "external_offer_id", "external_product_id", "ean", "valid_from", "valid_to", "collected_at", "valid", "dedupe_key"):
        op.create_index(f"ix_web_offer_audit_items_{column}", "web_offer_audit_items", [column])


def downgrade() -> None:
    op.drop_table("web_offer_audit_items")
    op.drop_table("web_offer_audit_runs")
