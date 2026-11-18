"""Identity: users, server-side sessions, login attempts. Global tables (no shop_id, no RLS)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, one_of, updated_at_col, uuid_pk

USER_STATUSES = ("active", "disabled")
LANGUAGES = ("hi", "hinglish", "en", "pa")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("phone ~ '^\\+91[6-9][0-9]{9}$'", name="phone_e164_in"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonnegative"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="name_length"),
        one_of("status", USER_STATUSES),
        one_of("preferred_language", LANGUAGES),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    phone: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    preferred_language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="hinglish"
    )
    # Argon2id encoded hash (algorithm, parameters and salt included). Never returned by APIs.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_shop_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shops.id", use_alter=True, name="fk_users_last_active_shop_id_shops")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AuthSession(Base):
    """Server-side session. Only the SHA-256 hash of the random token is stored."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_sha256"),
        Index(
            "ix_auth_sessions_user_id_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    active_shop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("shops.id"))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_col()
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(32))


class LoginAttempt(Base):
    """Rate limiting / lockout evidence. Phone and IP are stored as keyed HMACs, never raw."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_phone_hash_attempted_at", "phone_hash", "attempted_at"),
        Index("ix_login_attempts_ip_hash_attempted_at", "ip_hash", "attempted_at"),
        one_of(
            "failure_reason",
            ("bad_credentials", "locked", "disabled", "rate_limited"),
            name="failure_reason_valid",
        ),
        CheckConstraint(
            "(succeeded AND failure_reason IS NULL)"
            " OR (NOT succeeded AND failure_reason IS NOT NULL)",
            name="failure_reason_matches_outcome",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(32))
    attempted_at: Mapped[datetime] = created_at_col()
