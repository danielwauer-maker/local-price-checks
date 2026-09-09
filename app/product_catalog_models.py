from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import MasterProduct


class MasterProductProfile(Base):
    """Additive structured metadata for Spareno's canonical product catalogue.

    ``MasterProduct`` remains the stable identity referenced by offers, shopping
    lists and observations. This 1:1 profile adds richer canonical attributes
    without rewriting the legacy table in place.
    """

    __tablename__ = "master_product_profiles"
    __table_args__ = (
        UniqueConstraint("master_product_id", name="uq_master_product_profile_product"),
        Index("ix_master_product_profiles_family_key", "family_key"),
        Index("ix_master_product_profiles_verification", "verification_status", "confidence"),
        Index("ix_master_product_profiles_package", "package_unit", "package_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    product_family: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    variant_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    family_key: Mapped[str | None] = mapped_column(String(320), nullable=True)
    package_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    package_unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    package_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparison_unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ingredients_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties_json: Mapped[str] = mapped_column(Text, default="{}")
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    data_source: Mapped[str] = mapped_column(String(80), default="legacy_backfill", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    master_product: Mapped[MasterProduct] = relationship()
