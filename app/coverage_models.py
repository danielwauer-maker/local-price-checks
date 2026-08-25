from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class CoverageRegion(Base):
    """Geographic rollout area shown to users and used for market onboarding."""

    __tablename__ = "coverage_regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    center_lat: Mapped[float] = mapped_column(Float)
    center_lng: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float, default=15.0)
    status: Mapped[str] = mapped_column(String(30), default="building", index=True)  # building/live/paused
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CoveragePostalCode(Base):
    """One selectable 5-digit rollout area in the admin coverage map.

    A postcode being enabled means Lokero should discover and validate markets
    there. It does *not* by itself make any market or offers public.
    """

    __tablename__ = "coverage_postal_codes"
    __table_args__ = (UniqueConstraint("postal_code", name="uq_coverage_postal_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    postal_code: Mapped[str] = mapped_column(String(5), index=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    geometry_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StoreDiscoveryCandidate(Base):
    """Staging record for a discovered market before it can become public.

    Discovery providers may be incomplete or stale. Candidates therefore remain
    separate from ``Store`` until address and coordinates have been validated.
    """

    __tablename__ = "store_discovery_candidates"
    __table_args__ = (UniqueConstraint("discovery_key", name="uq_store_discovery_candidate_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    discovery_key: Mapped[str] = mapped_column(String(240), index=True)
    postal_code: Mapped[str] = mapped_column(String(5), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(180))
    address: Mapped[str] = mapped_column(String(220))
    city: Mapped[str] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50), default="osm", index=True)
    source_external_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="discovered", index=True)  # discovered/verified/rejected/promoted
    address_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    coordinates_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    official_source_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    matched_store = relationship("Store")
