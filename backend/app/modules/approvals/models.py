"""Owner approval requests for staff operations (credit over limit, stock override)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    created_at_col,
    one_of,
    paise,
    shop_id_col,
    tenant_fk,
    tenant_key,
    updated_at_col,
    uuid_pk,
)

APPROVAL_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "expired",
    "cancelled",
    "executed",
    "failed",
)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        tenant_key(),
        tenant_fk("customer_id", "customers"),
        tenant_fk(
            "pending_action_id",
            "pending_actions",
            use_alter=True,
            name="fk_approval_requests_pending_action",
        ),
        tenant_fk("resulting_transaction_id", "business_transactions"),
        one_of("request_type", ("credit_over_limit", "stock_override")),
        one_of("status", APPROVAL_STATUSES),
        CheckConstraint(
            "decided_by_user_id IS NULL OR decided_by_user_id <> requested_by_user_id",
            name="decider_not_requester",
        ),
        CheckConstraint(
            "(status IN ('pending', 'expired', 'cancelled')) = (decided_by_user_id IS NULL)",
            name="decision_matches_status",
        ),
        CheckConstraint(
            "(status = 'executed') = (resulting_transaction_id IS NOT NULL)",
            name="executed_has_transaction",
        ),
        CheckConstraint("amount_paise IS NULL OR amount_paise > 0", name="amount_positive"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index(
            "uq_approval_requests_open_per_pending_action",
            "shop_id",
            "pending_action_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND pending_action_id IS NOT NULL"),
        ),
        Index("ix_approval_requests_shop_id_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    request_type: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    amount_paise: Mapped[int | None] = paise(nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason_from_requester: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resulting_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
