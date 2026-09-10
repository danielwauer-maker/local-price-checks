from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import MediaAsset


class ProductMediaLibraryMetadata(Base):
    """Quality, provenance and review state for one existing ``MediaAsset``.

    BR-1D deliberately extends the existing media architecture instead of
    introducing another product-image identity. ``MediaAsset`` stays the stable
    image record; ``MediaAssetMetadata`` keeps source ranking/identity; this
    one-to-one table adds the richer library fields needed for safe automatic
    selection and later admin review.
    """

    __tablename__ = "product_media_library_metadata"
    __table_args__ = (
        UniqueConstraint("media_asset_id", name="uq_product_media_library_asset"),
        Index("ix_product_media_library_review", "verification_status", "is_broken"),
        Index("ix_product_media_library_quality", "quality_score", "manual_preferred"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    media_asset_id: Mapped[int] = mapped_column(ForeignKey("media_assets.id"), index=True)

    # Provenance / observation history. The original source URL remains on
    # MediaAsset so old data and callers do not need to move.
    source_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    retailer: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Technical quality. Hashes are descriptive only; BR-1D never merges
    # products or media records merely because two files look identical.
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aspect_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_logo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Human review state. Rejected/broken images remain in the database for
    # provenance and auditability but are excluded from public selection.
    verification_status: Mapped[str] = mapped_column(String(30), default="unreviewed", index=True)
    is_broken: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    manual_preferred: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    media_asset: Mapped[MediaAsset] = relationship()
