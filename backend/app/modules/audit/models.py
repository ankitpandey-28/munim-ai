"""Append-only audit log. shop_id is NULL for platform/identity events (e.g. login)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import SOURCES, Base, one_of, uuid_pk


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        one_of("actor_type", ("user", "system", "platform_admin", "anonymous")),
        one_of("source", SOURCES),
        Index("ix_audit_logs_shop_id_created_at", "shop_id", "created_at"),
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor_user_id_created_at", "actor_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("shops.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Plain ids (no FKs): the audit trail must survive independently of what it describes.
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="manual")
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    # Python-side default: shop-less rows are write-only under RLS, so the INSERT must not need
    # RETURNING (which PostgreSQL checks against the SELECT policy).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
