from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import UserProfile


class UserClient(Base):
    """Anonymous browser/PWA client mapped to one persistent user profile."""

    __tablename__ = "user_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), unique=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    pwa_installed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pwa_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    platform: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[UserProfile] = relationship()
    device: Mapped["ClientDevice | None"] = relationship(back_populates="client", uselist=False)


class ClientDevice(Base):
    """Normalized, privacy-conscious device metadata for one anonymous client."""

    __tablename__ = "client_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user_clients.id"), unique=True, index=True)
    device_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    device_type: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    os_name: Mapped[str] = mapped_column(String(40), default="Unknown", index=True)
    os_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    browser_name: Mapped[str] = mapped_column(String(40), default="Unknown", index=True)
    browser_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(80), nullable=True)
    mobile_hint: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    touch_points: Mapped[int] = mapped_column(Integer, default=0)
    screen_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pixel_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    standalone: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    client: Mapped[UserClient] = relationship(back_populates="device")


class ClientPricingFeedback(Base):
    """One pricing/value survey answer per anonymous browser/PWA client."""

    __tablename__ = "client_pricing_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user_clients.id"), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    savings_value: Mapped[str] = mapped_column(String(24), index=True)
    monthly_price: Mapped[str] = mapped_column(String(12), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ClientAppRating(Base):
    """One star rating and optional improvement comment per anonymous client.

    Kept in a separate additive table so existing SQLite installations receive
    the feature through ``Base.metadata.create_all`` without ALTER TABLE work.
    """

    __tablename__ = "client_app_ratings"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user_clients.id"), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
