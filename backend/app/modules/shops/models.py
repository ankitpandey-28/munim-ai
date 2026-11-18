"""Shops (tenants), memberships and per-shop settings."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    created_at_col,
    one_of,
    paise,
    shop_id_col,
    tenant_key,
    updated_at_col,
    uuid_pk,
)

SHOP_STATUSES = ("active", "suspended")
MEMBER_ROLES = ("owner", "admin", "staff")
MEMBER_STATUSES = ("active", "removed")


class Shop(Base):
    __tablename__ = "shops"
    __table_args__ = (
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$'", name="pincode_format"),
        one_of("status", SHOP_STATUSES),
        one_of("default_language", ("hi", "hinglish", "en", "pa")),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    business_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="kirana")
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    pincode: Mapped[str | None] = mapped_column(String(6))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Kolkata")
    default_language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="hinglish"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ShopMember(Base):
    __tablename__ = "shop_members"
    __table_args__ = (
        tenant_key(),
        UniqueConstraint("shop_id", "user_id"),
        one_of("role", MEMBER_ROLES),
        one_of("status", MEMBER_STATUSES),
        CheckConstraint(
            "credit_limit_paise IS NULL OR credit_limit_paise >= 0", name="credit_limit_nonnegative"
        ),
        CheckConstraint(
            "(status = 'removed') = (removed_at IS NOT NULL)", name="removed_at_matches_status"
        ),
        Index(
            "ix_shop_members_user_id_active", "user_id", postgresql_where=text("status = 'active'")
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Per-transaction udhaar limit for staff (docs Q-21); NULL = shop default applies.
    credit_limit_paise: Mapped[int | None] = paise(nullable=True)
    permission_overrides: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    joined_at: Mapped[datetime] = created_at_col()
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ShopSettings(Base):
    """One row per shop. Validated JSON document (schema owned by the shops module)."""

    __tablename__ = "shop_settings"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("shops.id"), primary_key=True)
    settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = updated_at_col()
