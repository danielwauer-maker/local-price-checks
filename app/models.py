from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    postal_code: Mapped[str] = mapped_column(String(10), index=True)
    city: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    benchmark_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), default="Local User")
    postal_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_km: Mapped[float] = mapped_column(Float, default=15.0)


class FavoriteStore(Base):
    __tablename__ = "favorite_stores"
    __table_args__ = (UniqueConstraint("user_id", "store_id", name="uq_favorite_store"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    store: Mapped[Store] = relationship()


class MasterProduct(Base):
    __tablename__ = "master_products"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    package_size: Mapped[str | None] = mapped_column(String(80), nullable=True)
    normalized_key: Mapped[str] = mapped_column(String(320), unique=True, index=True)


class ProductBarcode(Base):
    __tablename__ = "product_barcodes"
    barcode: Mapped[str] = mapped_column(String(14), primary_key=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    source: Mapped[str] = mapped_column(String(40), default="user")
    master_product: Mapped[MasterProduct] = relationship()


class FavoriteProduct(Base):
    __tablename__ = "favorite_products"
    __table_args__ = (UniqueConstraint("user_id", "master_product_id", name="uq_favorite_product"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    product: Mapped[MasterProduct] = relationship()


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    __table_args__ = (UniqueConstraint("user_id", "master_product_id", name="uq_shopping_item"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    product: Mapped[MasterProduct] = relationship()


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("store_id", "master_product_id", "valid_from", "price", name="uq_offer"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    price: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, index=True)
    valid_to: Mapped[date] = mapped_column(Date, index=True)
    local_store_offer: Mapped[bool] = mapped_column(Boolean, default=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    store: Mapped[Store] = relationship()
    product: Mapped[MasterProduct] = relationship()


class OfferOccurrence(Base):
    """One concrete appearance of an offer in a retailer prospect.

    ``Offer`` intentionally stays deduplicated for public comparison. This table
    keeps every distinct source occurrence (especially repeated appearances on
    different pages) together with the retailer's original compact detail line.
    Re-running the same scrape does not create duplicates because the
    occurrence fingerprint is stable for offer/page/source text.
    """
    __tablename__ = "offer_occurrences"
    __table_args__ = (UniqueConstraint("offer_id", "occurrence_fingerprint", name="uq_offer_occurrence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    prospect_page: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    occurrence_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    detail_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_size: Mapped[str | None] = mapped_column(String(80), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    offer: Mapped[Offer] = relationship()


class OfferPriceReference(Base):
    """Optional UVP/regular-price comparison for a concrete offer.

    Kept in an additive table so existing SQLite installations do not require an
    ALTER TABLE migration. A row is created only when the retailer actually
    supplies a reference price above the offer price.
    """
    __tablename__ = "offer_price_references"
    __table_args__ = (UniqueConstraint("offer_id", name="uq_offer_price_reference"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    reference_price: Mapped[float] = mapped_column(Float)
    reference_type: Mapped[str] = mapped_column(String(30), default="regular")
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    offer: Mapped[Offer] = relationship()


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(80), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    offers_received: Mapped[int] = mapped_column(Integer, default=0)
    offers_imported: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    store: Mapped[Store] = relationship()


class CollectionRunProgress(Base):
    """Persisted, queryable progress for long-running collector phases.

    This is an additive table instead of new ``collection_runs`` columns so
    existing production SQLite databases can adopt it through ``create_all``
    without an in-place schema migration.
    """

    __tablename__ = "collection_run_progress"
    __table_args__ = (UniqueConstraint("run_id", name="uq_collection_run_progress_run"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    phase: Mapped[str] = mapped_column(String(50), default="starting", index=True)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pages_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_structured: Mapped[int] = mapped_column(Integer, default=0)
    pages_ocr: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    assets_cached: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    run: Mapped[CollectionRun] = relationship()


class ProductCategory(Base):
    __tablename__ = "product_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)


class ProductAdminData(Base):
    __tablename__ = "product_admin_data"
    __table_args__ = (UniqueConstraint("master_product_id", name="uq_product_admin_data"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"), nullable=True, index=True)
    name_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    category_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    product: Mapped[MasterProduct] = relationship()
    category: Mapped[ProductCategory | None] = relationship()


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    __table_args__ = (UniqueConstraint("alias_key", name="uq_product_alias_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    alias_key: Mapped[str] = mapped_column(String(320), index=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    source: Mapped[str] = mapped_column(String(40), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    product: Mapped[MasterProduct] = relationship()


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    master_product_id: Mapped[int | None] = mapped_column(ForeignKey("master_products.id"), nullable=True, index=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True, index=True)
    retailer: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(240), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminSetting(Base):
    __tablename__ = "admin_settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(100), default="admin")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
