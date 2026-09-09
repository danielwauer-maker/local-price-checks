"""add BR-1A source products, price observations and daily runs

Revision ID: 20260909_01
Revises: 20260903_01
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260909_01"
down_revision: Union[str, None] = "20260903_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("stores_planned", sa.Integer(), nullable=False),
        sa.Column("stores_succeeded", sa.Integer(), nullable=False),
        sa.Column("stores_failed", sa.Integer(), nullable=False),
        sa.Column("stores_blocked", sa.Integer(), nullable=False),
        sa.Column("offers_observed", sa.Integer(), nullable=False),
        sa.Column("products_created", sa.Integer(), nullable=False),
        sa.Column("price_observations", sa.Integer(), nullable=False),
        sa.Column("normal_price_observations", sa.Integer(), nullable=False),
        sa.Column("reference_prices", sa.Integer(), nullable=False),
        sa.Column("product_match_rate", sa.Float(), nullable=False),
        sa.Column("image_coverage", sa.Float(), nullable=False),
        sa.Column("price_coverage", sa.Float(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("blockers_json", sa.Text(), nullable=False),
        sa.Column("collection_run_ids_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_date", name="uq_daily_collection_run_date"),
    )
    op.create_index("ix_daily_collection_runs_run_date", "daily_collection_runs", ["run_date"])
    op.create_index("ix_daily_collection_runs_started_at", "daily_collection_runs", ["started_at"])
    op.create_index("ix_daily_collection_runs_status", "daily_collection_runs", ["status"])
    op.create_index("ix_daily_collection_runs_status_started", "daily_collection_runs", ["status", "started_at"])

    op.create_table(
        "source_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("external_product_id", sa.String(160), nullable=True),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(240), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.UniqueConstraint("identity_key", name="uq_source_product_identity"),
    )
    for name, columns in (
        ("ix_source_products_master_product_id", ["master_product_id"]),
        ("ix_source_products_store_id", ["store_id"]),
        ("ix_source_products_retailer", ["retailer"]),
        ("ix_source_products_source_key", ["source_key"]),
        ("ix_source_products_external_product_id", ["external_product_id"]),
        ("ix_source_products_last_observed_at", ["last_observed_at"]),
        ("ix_source_products_master_retailer", ["master_product_id", "retailer"]),
        ("ix_source_products_store_source", ["store_id", "source_key"]),
    ):
        op.create_index(name, "source_products", columns)

    op.create_table(
        "price_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=False),
        sa.Column("source_product_id", sa.Integer(), sa.ForeignKey("source_products.id"), nullable=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("unit_price_unit", sa.String(20), nullable=True),
        sa.Column("price_type", sa.String(30), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(160), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("collection_run_id", sa.Integer(), sa.ForeignKey("collection_runs.id"), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_price_observation_dedupe"),
    )
    for name, columns in (
        ("ix_price_observations_master_product_id", ["master_product_id"]),
        ("ix_price_observations_source_product_id", ["source_product_id"]),
        ("ix_price_observations_store_id", ["store_id"]),
        ("ix_price_observations_retailer", ["retailer"]),
        ("ix_price_observations_price_type", ["price_type"]),
        ("ix_price_observations_valid_from", ["valid_from"]),
        ("ix_price_observations_valid_to", ["valid_to"]),
        ("ix_price_observations_observed_at", ["observed_at"]),
        ("ix_price_observations_source", ["source"]),
        ("ix_price_observations_external_id", ["external_id"]),
        ("ix_price_observations_product_observed", ["master_product_id", "observed_at"]),
        ("ix_price_observations_product_store_observed", ["master_product_id", "store_id", "observed_at"]),
        ("ix_price_observations_retailer_observed", ["retailer", "observed_at"]),
        ("ix_price_observations_run", ["collection_run_id"]),
        ("ix_price_observations_type_observed", ["price_type", "observed_at"]),
    ):
        op.create_index(name, "price_observations", columns)


def downgrade() -> None:
    op.drop_table("price_observations")
    op.drop_table("source_products")
    op.drop_table("daily_collection_runs")
