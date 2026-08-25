"""add postcode coverage and market discovery staging

Revision ID: 20260825_03
Revises: 20260825_02
Create Date: 2026-08-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_03"
down_revision: Union[str, None] = "20260825_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coverage_postal_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("postal_code", sa.String(length=5), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("center_lat", sa.Float(), nullable=True),
        sa.Column("center_lng", sa.Float(), nullable=True),
        sa.Column("geometry_source", sa.String(length=80), nullable=True),
        sa.Column("geometry_geojson", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("postal_code", name="uq_coverage_postal_code"),
    )
    op.create_index("ix_coverage_postal_codes_postal_code", "coverage_postal_codes", ["postal_code"], unique=False)
    op.create_index("ix_coverage_postal_codes_city", "coverage_postal_codes", ["city"], unique=False)
    op.create_index("ix_coverage_postal_codes_enabled", "coverage_postal_codes", ["enabled"], unique=False)
    op.create_index("ix_coverage_postal_codes_created_at", "coverage_postal_codes", ["created_at"], unique=False)

    op.create_table(
        "store_discovery_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("discovery_key", sa.String(length=240), nullable=False),
        sa.Column("postal_code", sa.String(length=5), nullable=False),
        sa.Column("retailer", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("address", sa.String(length=220), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="osm"),
        sa.Column("source_external_id", sa.String(length=160), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="discovered"),
        sa.Column("address_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("coordinates_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("official_source_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_note", sa.Text(), nullable=True),
        sa.Column("matched_store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("discovery_key", name="uq_store_discovery_candidate_key"),
    )
    for name, cols in (
        ("ix_store_discovery_candidates_discovery_key", ["discovery_key"]),
        ("ix_store_discovery_candidates_postal_code", ["postal_code"]),
        ("ix_store_discovery_candidates_retailer", ["retailer"]),
        ("ix_store_discovery_candidates_source", ["source"]),
        ("ix_store_discovery_candidates_source_external_id", ["source_external_id"]),
        ("ix_store_discovery_candidates_status", ["status"]),
        ("ix_store_discovery_candidates_address_verified", ["address_verified"]),
        ("ix_store_discovery_candidates_coordinates_verified", ["coordinates_verified"]),
        ("ix_store_discovery_candidates_official_source_verified", ["official_source_verified"]),
        ("ix_store_discovery_candidates_matched_store_id", ["matched_store_id"]),
        ("ix_store_discovery_candidates_created_at", ["created_at"]),
    ):
        op.create_index(name, "store_discovery_candidates", cols, unique=False)


def downgrade() -> None:
    op.drop_table("store_discovery_candidates")
    op.drop_table("coverage_postal_codes")
