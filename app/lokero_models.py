from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import MasterProduct, Store, UserProfile


class NormalPriceObservation(Base):
    """Observed non-promotional/reference price used to judge real discounts.

    Rows are intentionally additive so existing SQLite installations can gain
    the table through Base.metadata.create_all without an in-place migration.
    """

    __tablename__ = "normal_price_observations"
    __table_args__ = (
        UniqueConstraint(
            "master_product_id",
            "store_id",
            "observed_at",
            "price",
            "source",
            name="uq_normal_price_observation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True, index=True)
    retailer: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_regular_price: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    product: Mapped[MasterProduct] = relationship()
    store: Mapped[Store | None] = relationship()


class ReviewerDeviceGrant(Base):
    """Temporary reviewer/admin capability bound to one anonymous PWA device."""

    __tablename__ = "reviewer_device_grants"

    client_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    granted_by: Mapped[str] = mapped_column(String(100), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RegionInterest(Base):
    """User request to be notified once Lokero reaches a postal code."""

    __tablename__ = "region_interests"
    __table_args__ = (
        UniqueConstraint("postal_code", "email", "user_id", name="uq_region_interest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    postal_code: Mapped[str] = mapped_column(String(10), index=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[UserProfile | None] = relationship()


class FavoriteProductPreference(Base):
    """Per-user preference controlling whether a favorite may be substituted."""

    __tablename__ = "favorite_product_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "master_product_id", name="uq_favorite_product_preference"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    allow_alternatives: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user: Mapped[UserProfile] = relationship()
    product: Mapped[MasterProduct] = relationship()
