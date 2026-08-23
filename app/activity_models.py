from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .client_models import UserClient
from .db import Base


class ClientUsageSession(Base):
    """Coarse anonymous usage session for one browser/PWA client.

    Sessions are server-side aggregates. We intentionally do not keep raw URL
    histories, query strings, product ids or other event payloads here.
    """

    __tablename__ = "client_usage_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user_clients.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    page_views: Mapped[int] = mapped_column(Integer, default=0)
    entry_page: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_page: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pwa: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    client: Mapped[UserClient] = relationship()


class ClientActivityDay(Base):
    """One daily aggregate per anonymous client.

    This is deliberately compact: main-section counters plus current aggregate
    state sizes. It is enough for engagement/retention analytics without
    storing a detailed browsing history.
    """

    __tablename__ = "client_activity_days"
    __table_args__ = (UniqueConstraint("client_id", "activity_date", name="uq_client_activity_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user_clients.id"), index=True)
    activity_date: Mapped[date] = mapped_column(Date, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    page_views: Mapped[int] = mapped_column(Integer, default=0)

    home_views: Mapped[int] = mapped_column(Integer, default=0)
    offers_views: Mapped[int] = mapped_column(Integer, default=0)
    favorites_views: Mapped[int] = mapped_column(Integer, default=0)
    shopping_views: Mapped[int] = mapped_column(Integer, default=0)
    stores_views: Mapped[int] = mapped_column(Integer, default=0)
    settings_views: Mapped[int] = mapped_column(Integer, default=0)
    store_detail_views: Mapped[int] = mapped_column(Integer, default=0)
    other_views: Mapped[int] = mapped_column(Integer, default=0)

    favorite_products_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_stores_count: Mapped[int] = mapped_column(Integer, default=0)
    shopping_items_count: Mapped[int] = mapped_column(Integer, default=0)

    client: Mapped[UserClient] = relationship()


class ClientFeatureUsage(Base):
    """Lifetime aggregate for an allow-listed feature name.

    Only the feature name and counters are stored; no product/store identifiers
    or arbitrary metadata are accepted.
    """

    __tablename__ = "client_feature_usage"
    __table_args__ = (UniqueConstraint("client_id", "feature", name="uq_client_feature_usage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("user_clients.id"), index=True)
    feature: Mapped[str] = mapped_column(String(50), index=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    first_used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    client: Mapped[UserClient] = relationship()
