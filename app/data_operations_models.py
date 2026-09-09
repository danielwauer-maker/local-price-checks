from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import CollectionRun, MasterProduct, Store


class SourceProduct(Base):
    """Stable retailer/source identity mapped to Spareno's master catalogue."""

    __tablename__ = "source_products"
    __table_args__ = (
        UniqueConstraint("identity_key", name="uq_source_product_identity"),
        Index("ix_source_products_master_retailer", "master_product_id", "retailer"),
        Index("ix_source_products_store_source", "store_id", "source_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    external_product_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    identity_key: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(240))
    first_observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    match_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    master_product: Mapped[MasterProduct] = relationship()
    store: Mapped[Store] = relationship()


class PriceObservation(Base):
    """Append-only price fact; one retry-safe fact per source/day/semantics.

    ``dedupe_key`` includes the UTC observation date, source identity, validity,
    price semantics and value. A retry therefore reuses the same fact while a
    later daily collection appends a new historical observation.
    """

    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_price_observation_dedupe"),
        Index("ix_price_observations_product_observed", "master_product_id", "observed_at"),
        Index("ix_price_observations_product_store_observed", "master_product_id", "store_id", "observed_at"),
        Index("ix_price_observations_retailer_observed", "retailer", "observed_at"),
        Index("ix_price_observations_run", "collection_run_id"),
        Index("ix_price_observations_type_observed", "price_type", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    source_product_id: Mapped[int | None] = mapped_column(ForeignKey("source_products.id"), nullable=True, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    price: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_type: Mapped[str] = mapped_column(String(30), index=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    collection_run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.id"), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    master_product: Mapped[MasterProduct] = relationship()
    source_product: Mapped[SourceProduct | None] = relationship()
    store: Mapped[Store] = relationship()
    collection_run: Mapped[CollectionRun | None] = relationship()


class DailyCollectionRun(Base):
    """One logical, idempotent Europe/Berlin daily orchestration run."""

    __tablename__ = "daily_collection_runs"
    __table_args__ = (
        UniqueConstraint("run_date", name="uq_daily_collection_run_date"),
        Index("ix_daily_collection_runs_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    stores_planned: Mapped[int] = mapped_column(Integer, default=0)
    stores_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    stores_failed: Mapped[int] = mapped_column(Integer, default=0)
    stores_blocked: Mapped[int] = mapped_column(Integer, default=0)
    offers_observed: Mapped[int] = mapped_column(Integer, default=0)
    products_created: Mapped[int] = mapped_column(Integer, default=0)
    price_observations: Mapped[int] = mapped_column(Integer, default=0)
    normal_price_observations: Mapped[int] = mapped_column(Integer, default=0)
    reference_prices: Mapped[int] = mapped_column(Integer, default=0)
    product_match_rate: Mapped[float] = mapped_column(Float, default=0.0)
    image_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    price_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    blockers_json: Mapped[str] = mapped_column(Text, default="[]")
    collection_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
