"""add BR-1C retailer product identity

Revision ID: 20260909_03
Revises: 20260909_02
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260909_03"
down_revision: Union[str, None] = "20260909_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retailer_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("master_product_id", sa.Integer(), sa.ForeignKey("master_products.id"), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("identity_type", sa.String(40), nullable=False),
        sa.Column("identity_value", sa.String(160), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(240), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.UniqueConstraint("identity_key", name="uq_retailer_product_identity"),
    )
    for name, columns in (
        ("ix_retailer_products_master_product_id", ["master_product_id"]),
        ("ix_retailer_products_retailer", ["retailer"]),
        ("ix_retailer_products_identity_type", ["identity_type"]),
        ("ix_retailer_products_identity_value", ["identity_value"]),
        ("ix_retailer_products_verification_status", ["verification_status"]),
        ("ix_retailer_products_last_observed_at", ["last_observed_at"]),
        ("ix_retailer_products_master_retailer", ["master_product_id", "retailer"]),
        ("ix_retailer_products_identity", ["retailer", "identity_type", "identity_value"]),
        ("ix_retailer_products_status", ["verification_status", "match_confidence"]),
    ):
        op.create_index(name, "retailer_products", columns)

    with op.batch_alter_table("source_products") as batch:
        batch.add_column(sa.Column("retailer_product_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_source_products_retailer_product_id",
            "retailer_products",
            ["retailer_product_id"],
            ["id"],
        )
        batch.create_index("ix_source_products_retailer_product_id", ["retailer_product_id"])
        batch.create_index("ix_source_products_retailer_product", ["retailer_product_id"])

    # Deliberately no historical auto-merge/backfill. Existing SourceProducts
    # keep their identity and observations untouched. Strong retailer identity
    # is attached only when the source is observed again with sufficient proof.


def downgrade() -> None:
    with op.batch_alter_table("source_products") as batch:
        batch.drop_index("ix_source_products_retailer_product")
        batch.drop_index("ix_source_products_retailer_product_id")
        batch.drop_constraint("fk_source_products_retailer_product_id", type_="foreignkey")
        batch.drop_column("retailer_product_id")
    op.drop_table("retailer_products")
