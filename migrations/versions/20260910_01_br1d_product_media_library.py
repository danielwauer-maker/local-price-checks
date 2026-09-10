"""add BR-1D product media library metadata

Revision ID: 20260910_01
Revises: 20260909_03
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260910_01"
down_revision: Union[str, None] = "20260909_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_media_library_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("media_asset_id", sa.Integer(), sa.ForeignKey("media_assets.id"), nullable=False),
        sa.Column("source_name", sa.String(120), nullable=True),
        sa.Column("retailer", sa.String(80), nullable=True),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("image_format", sa.String(20), nullable=True),
        sa.Column("aspect_ratio", sa.Float(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("perceptual_hash", sa.String(32), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("is_placeholder", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_logo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_status", sa.String(30), nullable=False, server_default="unreviewed"),
        sa.Column("is_broken", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("manual_preferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("media_asset_id", name="uq_product_media_library_asset"),
    )
    for name, columns in (
        ("ix_product_media_library_metadata_media_asset_id", ["media_asset_id"]),
        ("ix_product_media_library_metadata_source_name", ["source_name"]),
        ("ix_product_media_library_metadata_retailer", ["retailer"]),
        ("ix_product_media_library_metadata_first_observed_at", ["first_observed_at"]),
        ("ix_product_media_library_metadata_last_observed_at", ["last_observed_at"]),
        ("ix_product_media_library_metadata_content_sha256", ["content_sha256"]),
        ("ix_product_media_library_metadata_perceptual_hash", ["perceptual_hash"]),
        ("ix_product_media_library_metadata_quality_score", ["quality_score"]),
        ("ix_product_media_library_metadata_is_placeholder", ["is_placeholder"]),
        ("ix_product_media_library_metadata_is_logo", ["is_logo"]),
        ("ix_product_media_library_metadata_verification_status", ["verification_status"]),
        ("ix_product_media_library_metadata_is_broken", ["is_broken"]),
        ("ix_product_media_library_metadata_manual_preferred", ["manual_preferred"]),
        ("ix_product_media_library_review", ["verification_status", "is_broken"]),
        ("ix_product_media_library_quality", ["quality_score", "manual_preferred"]),
    ):
        op.create_index(name, "product_media_library_metadata", columns)

    # Existing MediaAsset rows are intentionally not rewritten or guessed.
    # Library metadata is populated lazily when an image is observed again or
    # explicitly reviewed. This preserves all existing image IDs/history.


def downgrade() -> None:
    op.drop_table("product_media_library_metadata")
