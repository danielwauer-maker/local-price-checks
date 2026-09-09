"""add BR-1B canonical master product profiles

Revision ID: 20260909_02
Revises: 20260909_01
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260909_02"
down_revision: Union[str, None] = "20260909_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "master_product_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=False),
        sa.Column("canonical_name", sa.String(240), nullable=False),
        sa.Column("manufacturer", sa.String(160), nullable=True),
        sa.Column("product_family", sa.String(180), nullable=True),
        sa.Column("variant_name", sa.String(180), nullable=True),
        sa.Column("family_key", sa.String(320), nullable=True),
        sa.Column("package_value", sa.Float(), nullable=True),
        sa.Column("package_unit", sa.String(24), nullable=True),
        sa.Column("package_count", sa.Integer(), nullable=True),
        sa.Column("total_quantity", sa.Float(), nullable=True),
        sa.Column("comparison_unit", sa.String(24), nullable=True),
        sa.Column("ingredients_text", sa.Text(), nullable=True),
        sa.Column("properties_json", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("data_source", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("master_product_id", name="uq_master_product_profile_product"),
    )
    for name, columns in (
        ("ix_master_product_profiles_master_product_id", ["master_product_id"]),
        ("ix_master_product_profiles_canonical_name", ["canonical_name"]),
        ("ix_master_product_profiles_manufacturer", ["manufacturer"]),
        ("ix_master_product_profiles_product_family", ["product_family"]),
        ("ix_master_product_profiles_verification_status", ["verification_status"]),
        ("ix_master_product_profiles_data_source", ["data_source"]),
        ("ix_master_product_profiles_family_key", ["family_key"]),
        ("ix_master_product_profiles_verification", ["verification_status", "confidence"]),
        ("ix_master_product_profiles_package", ["package_unit", "package_value"]),
    ):
        op.create_index(name, "master_product_profiles", columns)

    # Every existing MasterProduct immediately receives a profile row. Richer
    # package/family metadata is filled conservatively by the application as
    # products are observed again. Identity FKs are intentionally untouched.
    connection = op.get_bind()
    now = sa.func.now()
    master_products = sa.table(
        "master_products",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
    )
    profiles = sa.table(
        "master_product_profiles",
        sa.column("master_product_id", sa.Integer()),
        sa.column("canonical_name", sa.String()),
        sa.column("family_key", sa.String()),
        sa.column("properties_json", sa.Text()),
        sa.column("verification_status", sa.String()),
        sa.column("confidence", sa.Float()),
        sa.column("data_source", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    connection.execute(
        profiles.insert().from_select(
            [
                "master_product_id",
                "canonical_name",
                "family_key",
                "properties_json",
                "verification_status",
                "confidence",
                "data_source",
                "created_at",
                "updated_at",
            ],
            sa.select(
                master_products.c.id,
                master_products.c.name,
                sa.null(),
                sa.literal("{}"),
                sa.literal("unverified"),
                sa.literal(0.0),
                sa.literal("legacy_backfill"),
                now,
                now,
            ),
        )
    )


def downgrade() -> None:
    op.drop_table("master_product_profiles")
