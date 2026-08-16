from __future__ import annotations

from datetime import date
from sqlalchemy import Boolean, Date, Float, ForeignKey, String, Text, UniqueConstraint
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
    __table_args__ = (
        UniqueConstraint("store_id", "master_product_id", "valid_from", "price", name="uq_offer"),
    )
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
