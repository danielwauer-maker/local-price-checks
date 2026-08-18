from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
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
    """Immutable archived copy of an original market prospect.

    Prospect remains the current/next pointer used by the UI. ProspectArchive is
    append-only by PDF hash so past prospect files stay available for audits and
    historical price verification even after current/next rotates.
    """

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
