from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import Store


class WebOfferAuditRun(Base):
    """An isolated, non-importing snapshot of one retailer web surface."""

    __tablename__ = "web_offer_audit_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    period_key: Mapped[str] = mapped_column(String(40), default="current", index=True)
    source_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    collector_path: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    error_type: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_price_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_image_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_package_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    comparison_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    store: Mapped[Store] = relationship()
    offers: Mapped[list["WebOfferAuditItem"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="WebOfferAuditItem.id"
    )


class WebOfferAuditItem(Base):
    """Normalized offer evidence; never consumed by the production offer API."""

    __tablename__ = "web_offer_audit_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("web_offer_audit_runs.id", ondelete="CASCADE"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    source_type: Mapped[str] = mapped_column(String(20), default="web")
    source_url: Mapped[str] = mapped_column(Text)
    external_offer_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    external_product_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    ean: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(180), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_text: Mapped[str | None] = mapped_column(String(160), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quantity_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    packaging_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    image_alt: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    validation_errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(420), index=True)

    run: Mapped[WebOfferAuditRun] = relationship(back_populates="offers")
    store: Mapped[Store] = relationship()
