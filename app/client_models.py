from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import UserProfile


class UserClient(Base):
    """Anonymous browser/PWA client mapped to one persistent user profile.

    This keeps user state separated without requiring account registration yet.
    A browser receives a durable opaque client key cookie and therefore keeps
    its own location, favorites and shopping state across visits.
    """

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
