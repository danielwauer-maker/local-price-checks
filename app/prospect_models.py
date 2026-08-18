from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import Offer, Store


class Prospect(Base):
    __tablename__ = "prospects"
    __table_args__ = (
        UniqueConstraint("store_id", "period_key", name="uq_store_prospect_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    period_key: Mapped[str] = mapped_column(String(40), index=True)  # current / next
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(Text)
    pdf_url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    store: Mapped[Store] = relationship()


class ProspectArchive(Base):
    """Immutable archived copy of an original market prospect."""

    __tablename__ = "prospect_archives"
    __table_args__ = (
        UniqueConstraint("store_id", "pdf_sha256", name="uq_store_prospect_pdf_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    retailer: Mapped[str] = mapped_column(String(80), index=True)
    period_key: Mapped[str] = mapped_column(String(40), index=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(Text)
    pdf_url: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pdf_sha256: Mapped[str] = mapped_column(String(64), index=True)
    pdf_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    store: Mapped[Store] = relationship()


class OfferProvenance(Base):
    """Links an imported offer to the exact archived prospect and PDF page."""

    __tablename__ = "offer_provenance"
    __table_args__ = (
        UniqueConstraint("offer_id", "prospect_archive_id", "prospect_page", name="uq_offer_prospect_page"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    prospect_archive_id: Mapped[int] = mapped_column(ForeignKey("prospect_archives.id"), index=True)
    prospect_page: Mapped[int] = mapped_column(Integer, index=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    offer: Mapped[Offer] = relationship()
    prospect_archive: Mapped[ProspectArchive] = relationship()


class ProspectOfferReview(Base):
    """Manual audit signal for one extracted offer/prospect-page match.

    These rows form a durable supervised-learning corpus. A review records what
    the extractor produced and, where supplied, the value an admin expected.
    """

    __tablename__ = "prospect_offer_reviews"
    __table_args__ = (
        UniqueConstraint("offer_provenance_id", name="uq_prospect_offer_review_provenance"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_provenance_id: Mapped[int] = mapped_column(ForeignKey("offer_provenance.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    issue_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    expected_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    expected_brand: Mapped[str | None] = mapped_column(String(160), nullable=True)
    expected_package_size: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expected_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(100), default="admin")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    provenance: Mapped[OfferProvenance] = relationship()


class ProspectMissingItem(Base):
    """Product visible in the original PDF but not extracted at all."""

    __tablename__ = "prospect_missing_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    prospect_archive_id: Mapped[int] = mapped_column(ForeignKey("prospect_archives.id"), index=True)
    prospect_page: Mapped[int] = mapped_column(Integer, index=True)
    expected_name: Mapped[str] = mapped_column(String(240))
    expected_brand: Mapped[str | None] = mapped_column(String(160), nullable=True)
    expected_package_size: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expected_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reported_by: Mapped[str] = mapped_column(String(100), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    prospect_archive: Mapped[ProspectArchive] = relationship()
