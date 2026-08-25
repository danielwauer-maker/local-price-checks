"""add product category hierarchy

Revision ID: 20260825_02
Revises: 20260825_01
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_02"
down_revision: Union[str, None] = "20260825_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("product_categories") as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_product_categories_parent_id_product_categories",
            "product_categories",
            ["parent_id"],
            ["id"],
        )
        batch_op.create_index("ix_product_categories_parent_id", ["parent_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("product_categories") as batch_op:
        batch_op.drop_index("ix_product_categories_parent_id")
        batch_op.drop_constraint("fk_product_categories_parent_id_product_categories", type_="foreignkey")
        batch_op.drop_column("parent_id")
