"""add bounded-read indexes for public offers and media

Revision ID: 20260903_01
Revises: 20260901_01
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260903_01"
down_revision: Union[str, None] = "20260901_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_offers_public_store_validity",
        "offers",
        ["store_id", "local_store_offer", "valid_from", "valid_to"],
    )
    op.create_index(
        "ix_offer_occurrences_offer_collected",
        "offer_occurrences",
        ["offer_id", "collected_at"],
    )
    op.create_index(
        "ix_media_assets_product_lookup",
        "media_assets",
        ["kind", "master_product_id", "active", "is_primary"],
    )
    op.create_index(
        "ix_media_assets_store_lookup",
        "media_assets",
        ["kind", "store_id", "active", "is_primary"],
    )
    op.create_index(
        "ix_media_assets_retailer_lookup",
        "media_assets",
        ["kind", "retailer", "active", "is_primary"],
    )
    op.create_index(
        "ix_normal_prices_product_store_current",
        "normal_price_observations",
        ["master_product_id", "store_id", "is_regular_price", "observed_at"],
    )
    op.create_index(
        "ix_normal_prices_product_retailer_current",
        "normal_price_observations",
        ["master_product_id", "retailer", "is_regular_price", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_normal_prices_product_retailer_current", table_name="normal_price_observations")
    op.drop_index("ix_normal_prices_product_store_current", table_name="normal_price_observations")
    op.drop_index("ix_media_assets_retailer_lookup", table_name="media_assets")
    op.drop_index("ix_media_assets_store_lookup", table_name="media_assets")
    op.drop_index("ix_media_assets_product_lookup", table_name="media_assets")
    op.drop_index("ix_offer_occurrences_offer_collected", table_name="offer_occurrences")
    op.drop_index("ix_offers_public_store_validity", table_name="offers")
