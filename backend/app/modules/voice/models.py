"""Voice infrastructure tables (schema only in Phase 2; no voice logic yet).

Raw audio is never stored: there is deliberately no audio column of any kind (FR-VOICE-17).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    created_at_col,
    one_of,
    shop_id_col,
    tenant_fk,
    tenant_key,
    updated_at_col,
    uuid_pk,
)

PENDING_ACTION_STATUSES = (
    "draft",
    "awaiting_confirmation",
    "awaiting_approval",
    "confirmed",
    "executed",
    "cancelled",
    "expired",
    "superseded",
    "failed",
    "rejected",
)


class VoiceSession(Base):
    __tablename__ = "voice_sessions"
    __table_args__ = (
        tenant_key(),
        tenant_fk(
            "active_pending_action_id",
            "pending_actions",
            use_alter=True,
            name="fk_voice_sessions_active_pending_action",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = created_at_col()
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[str | None] = mapped_column(String(10))
    active_pending_action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class VoiceCommand(Base):
    __tablename__ = "voice_commands"
    __table_args__ = (
        tenant_key(),
        tenant_fk("session_id", "voice_sessions"),
        one_of("input_type", ("audio", "text")),
        one_of(
            "outcome",
            ("answered", "clarification_requested", "pending_action_created", "rejected", "error"),
        ),
        CheckConstraint(
            "audio_duration_ms IS NULL OR audio_duration_ms >= 0", name="duration_nonnegative"
        ),
        CheckConstraint(
            "stt_confidence IS NULL OR (stt_confidence >= 0 AND stt_confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_voice_commands_shop_id_created_at", "shop_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    input_type: Mapped[str] = mapped_column(String(8), nullable=False)
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer)
    audio_mime: Mapped[str | None] = mapped_column(String(64))
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stt_provider: Mapped[str | None] = mapped_column(String(32))
    stt_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    detected_language: Mapped[str | None] = mapped_column(String(10))
    llm_provider: Mapped[str | None] = mapped_column(String(32))
    llm_model: Mapped[str | None] = mapped_column(String(64))
    validated_intent: Mapped[str | None] = mapped_column(String(48))
    validated_arguments: Mapped[dict | None] = mapped_column(JSONB)
    validation_errors: Mapped[dict | None] = mapped_column(JSONB)
    resolution_summary: Mapped[dict | None] = mapped_column(JSONB)
    response_template_code: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[dict | None] = mapped_column(JSONB)
    cost_estimate_micros: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at_col()


class PendingAction(Base):
    __tablename__ = "pending_actions"
    __table_args__ = (
        tenant_key(),
        tenant_fk("voice_command_id", "voice_commands"),
        tenant_fk("session_id", "voice_sessions"),
        tenant_fk("supersedes_id", "pending_actions"),
        tenant_fk("approval_request_id", "approval_requests"),
        tenant_fk("executed_transaction_id", "business_transactions"),
        one_of("status", PENDING_ACTION_STATUSES),
        one_of("risk_level", ("low", "medium", "high")),
        one_of("confirmation_method", ("tap", "voice")),
        CheckConstraint(
            "(status = 'executed') = (executed_transaction_id IS NOT NULL)",
            name="executed_has_transaction",
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        # At most one action awaiting confirmation per voice session.
        Index(
            "uq_pending_actions_awaiting_per_session",
            "shop_id",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'awaiting_confirmation' AND session_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    voice_command_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    intent: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="draft")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_method: Mapped[str | None] = mapped_column(String(8))
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    executed_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
