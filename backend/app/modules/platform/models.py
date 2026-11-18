"""Platform infrastructure tables: idempotency keys and the PostgreSQL-backed job queue."""

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
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, one_of, updated_at_col, uuid_pk


class IdempotencyKey(Base):
    """A completed idempotent request. The row is inserted at the start of the business
    transaction and committed with it, so a visible row always means "completed"."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint("length(key) BETWEEN 8 AND 128", name="key_length"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index(
            "uq_idempotency_keys_shop_user_key",
            "shop_id",
            "user_id",
            "key",
            unique=True,
            postgresql_where=text("shop_id IS NOT NULL"),
        ),
        Index(
            "uq_idempotency_keys_user_key_no_shop",
            "user_id",
            "key",
            unique=True,
            postgresql_where=text("shop_id IS NULL"),
        ),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # NULL only for requests made before a shop exists (e.g. creating the first shop).
    shop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("shops.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Job(Base):
    """Background job queue (claimed with SELECT ... FOR UPDATE SKIP LOCKED). Global table."""

    __tablename__ = "jobs"
    __table_args__ = (
        one_of("status", ("queued", "running", "succeeded", "failed")),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        Index("ix_jobs_status_run_after", "status", "run_after"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("shops.id"))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
