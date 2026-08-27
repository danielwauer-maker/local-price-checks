from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import MasterProduct, UserProfile


class SharedShoppingList(Base):
    """A named shopping list that can be edited by multiple linked accounts."""

    __tablename__ = "shared_shopping_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Meine Einkaufsliste")
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner: Mapped[UserProfile] = relationship(foreign_keys=[owner_user_id])


class SharedShoppingListMember(Base):
    __tablename__ = "shared_shopping_list_members"
    __table_args__ = (UniqueConstraint("list_id", "user_id", name="uq_shared_list_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("shared_shopping_lists.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="editor")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    user: Mapped[UserProfile] = relationship()


class SharedShoppingListInvite(Base):
    __tablename__ = "shared_shopping_list_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("shared_shopping_lists.id"), index=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    invited_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)


class SharedShoppingListItem(Base):
    __tablename__ = "shared_shopping_list_items"
    __table_args__ = (UniqueConstraint("list_id", "master_product_id", name="uq_shared_list_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("shared_shopping_lists.id"), index=True)
    master_product_id: Mapped[int | None] = mapped_column(ForeignKey("master_products.id"), nullable=True, index=True)
    manual_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    checked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    added_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    checked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    product: Mapped[MasterProduct | None] = relationship()
    added_by: Mapped[UserProfile | None] = relationship(foreign_keys=[added_by_user_id])
    checked_by: Mapped[UserProfile | None] = relationship(foreign_keys=[checked_by_user_id])


class SharedShoppingListUserState(Base):
    __tablename__ = "shared_shopping_list_user_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), primary_key=True)
    active_list_id: Mapped[int] = mapped_column(ForeignKey("shared_shopping_lists.id"), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FavoriteShare(Base):
    """Stable, revocable public share identity for a user's favorite products."""

    __tablename__ = "favorite_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), unique=True, index=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner: Mapped[UserProfile] = relationship()


class FavoriteShareItemVisibility(Base):
    """Per-favorite visibility. A missing row means visible by default."""

    __tablename__ = "favorite_share_item_visibility"
    __table_args__ = (UniqueConstraint("owner_user_id", "master_product_id", name="uq_favorite_share_item_visibility"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    master_product_id: Mapped[int] = mapped_column(ForeignKey("master_products.id"), index=True)
    visible: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FavoriteShareSubscription(Base):
    """A saved 'favorites from a friend' subscription."""

    __tablename__ = "favorite_share_subscriptions"
    __table_args__ = (UniqueConstraint("subscriber_user_id", "share_id", name="uq_favorite_share_subscription"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subscriber_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    share_id: Mapped[int] = mapped_column(ForeignKey("favorite_shares.id"), index=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
