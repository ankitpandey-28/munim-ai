"""Ledger core: the header row of every money/stock operation (database-design.md §4.5, §5.1)."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    SOURCES,
    Base,
    created_at_col,
    one_of,
    shop_id_col,
    tenant_fk,
    tenant_key,
    uuid_pk,
)

TXN_TYPES = (
    "sale",
    "credit_given",
    "credit_collection",
    "refund",
    "expense",
    "stock_adjustment",
    "stock_count",
    "goods_receipt",
    "credit_write_off",
    "opening_balance",
    "reversal",
)
TXN_TYPES_REQUIRING_REASON = ("reversal", "credit_write_off", "stock_adjustment", "stock_count")


class BusinessTransaction(Base):
    """Append-only header. Only ``status`` and ``reversed_by_transaction_id`` may change, and only
    by posting a linked reversal (enforced by column grants + immutability trigger)."""

    __tablename__ = "business_transactions"
    __table_args__ = (
        tenant_key(),
        tenant_fk("reverses_transaction_id", "business_transactions"),
        tenant_fk("reversed_by_transaction_id", "business_transactions"),
        tenant_fk(
            "approval_request_id",
            "approval_requests",
            use_alter=True,
            name="fk_business_transactions_approval_request",
        ),
        tenant_fk(
            "pending_action_id",
            "pending_actions",
            use_alter=True,
            name="fk_business_transactions_pending_action",
        ),
        one_of("txn_type", TXN_TYPES),
        one_of("status", ("posted", "reversed")),
        one_of("source", SOURCES),
        one_of("override_type", ("insufficient_stock",)),
        CheckConstraint(
            "(txn_type = 'reversal') = (reverses_transaction_id IS NOT NULL)",
            name="reversal_links_original",
        ),
        CheckConstraint(
            "(status = 'reversed') = (reversed_by_transaction_id IS NOT NULL)",
            name="reversed_status_has_link",
        ),
        CheckConstraint(
            "NOT (txn_type = 'reversal' AND status = 'reversed')", name="reversal_not_reversible"
        ),
        CheckConstraint(
            "reverses_transaction_id IS NULL OR reverses_transaction_id <> id",
            name="not_self_reversal",
        ),
        CheckConstraint(
            "(override_type IS NULL AND override_reason_code IS NULL"
            " AND override_by_user_id IS NULL)"
            " OR (override_type IS NOT NULL AND override_reason_code IS NOT NULL"
            " AND override_by_user_id IS NOT NULL)",
            name="override_all_or_nothing",
        ),
        CheckConstraint(
            "txn_type NOT IN ("
            + ", ".join(f"'{t}'" for t in TXN_TYPES_REQUIRING_REASON)
            + ") OR length(trim(coalesce(reason, ''))) > 0",
            name="reason_required",
        ),
        CheckConstraint(
            "approved_by_user_id IS NULL OR approved_by_user_id <> initiated_by_user_id",
            name="approver_not_initiator",
        ),
        # A transaction can be reversed at most once.
        Index(
            "uq_business_transactions_reverses_transaction_id",
            "shop_id",
            "reverses_transaction_id",
            unique=True,
            postgresql_where=text("reverses_transaction_id IS NOT NULL"),
        ),
        Index("ix_business_transactions_shop_id_business_date", "shop_id", "business_date"),
        Index(
            "ix_business_transactions_shop_id_txn_type_occurred_at",
            "shop_id",
            "txn_type",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    txn_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="posted")
    reverses_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reversed_by_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    override_type: Mapped[str | None] = mapped_column(String(24))
    override_reason_code: Mapped[str | None] = mapped_column(String(32))
    override_note: Mapped[str | None] = mapped_column(Text)
    override_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="manual")
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    idempotency_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
