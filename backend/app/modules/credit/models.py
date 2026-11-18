"""Udhaar ledger, payments (all money movements) and payment allocations."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    PAYMENT_MODES,
    Base,
    created_at_col,
    one_of,
    paise,
    shop_id_col,
    tenant_fk,
    tenant_key,
    uuid_pk,
)

CREDIT_ENTRY_TYPES = (
    "opening_balance",
    "credit_given",
    "sale_credit",
    "payment_received",
    "advance_applied",
    "adjustment_increase",
    "adjustment_decrease",
    "write_off",
    "reversal",
)


class CreditEntry(Base):
    """Append-only. customers.balance_paise = SUM(amount_paise) (invariant I2)."""

    __tablename__ = "credit_entries"
    __table_args__ = (
        tenant_key(),
        tenant_fk("transaction_id", "business_transactions"),
        tenant_fk("customer_id", "customers"),
        tenant_fk("sale_id", "sales"),
        tenant_fk("payment_id", "payments"),
        tenant_fk("reverses_entry_id", "credit_entries"),
        one_of("entry_type", CREDIT_ENTRY_TYPES),
        CheckConstraint("amount_paise <> 0", name="amount_nonzero"),
        CheckConstraint(
            "settled_paise >= 0 AND settled_paise <= greatest(amount_paise, 0)",
            name="settled_within_amount",
        ),
        CheckConstraint(
            "is_open = (amount_paise > 0 AND settled_paise < amount_paise)",
            name="is_open_consistent",
        ),
        CheckConstraint(
            "entry_type <> 'sale_credit' OR sale_id IS NOT NULL", name="sale_credit_has_sale"
        ),
        CheckConstraint(
            "entry_type <> 'payment_received' OR payment_id IS NOT NULL",
            name="payment_entry_has_payment",
        ),
        CheckConstraint(
            "(entry_type = 'reversal') = (reverses_entry_id IS NOT NULL)",
            name="reversal_links_original",
        ),
        Index(
            "ix_credit_entries_shop_id_customer_id_occurred_at",
            "shop_id",
            "customer_id",
            "occurred_at",
        ),
        Index(
            "ix_credit_entries_open_dues",
            "shop_id",
            "customer_id",
            "occurred_at",
            postgresql_where=text("is_open"),
        ),
        Index("ix_credit_entries_shop_id_business_date", "shop_id", "business_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_paise: Mapped[int] = paise()
    balance_after_paise: Mapped[int] = paise()
    sale_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    settled_paise: Mapped[int] = paise(default=0)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Payment(Base):
    """Every money movement with a customer (cash collection record). Append-only."""

    __tablename__ = "payments"
    __table_args__ = (
        tenant_key(),
        tenant_fk("transaction_id", "business_transactions"),
        tenant_fk("customer_id", "customers"),
        tenant_fk("sale_id", "sales"),
        tenant_fk("reverses_payment_id", "payments"),
        one_of("direction", ("in", "out")),
        one_of("purpose", ("sale_tender", "credit_collection", "refund")),
        one_of("mode", PAYMENT_MODES),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        CheckConstraint(
            "purpose <> 'sale_tender' OR (direction = 'in' AND sale_id IS NOT NULL)",
            name="sale_tender_shape",
        ),
        CheckConstraint(
            "purpose <> 'credit_collection' OR (direction = 'in' AND customer_id IS NOT NULL)",
            name="credit_collection_shape",
        ),
        CheckConstraint("purpose <> 'refund' OR direction = 'out'", name="refund_is_outgoing"),
        CheckConstraint(
            "allocated_paise >= 0 AND unallocated_paise >= 0", name="allocation_amounts_nonnegative"
        ),
        CheckConstraint(
            "(purpose = 'credit_collection' AND reverses_payment_id IS NULL"
            " AND allocated_paise + unallocated_paise = amount_paise)"
            " OR ((purpose <> 'credit_collection' OR reverses_payment_id IS NOT NULL)"
            " AND allocated_paise = 0 AND unallocated_paise = 0)",
            name="allocation_balance",
        ),
        Index("ix_payments_shop_id_business_date", "shop_id", "business_date"),
        Index("ix_payments_shop_id_customer_id", "shop_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_paise: Mapped[int] = paise()
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    upi_reference: Mapped[str | None] = mapped_column(String(64))
    allocated_paise: Mapped[int] = paise(default=0)
    unallocated_paise: Mapped[int] = paise(default=0)
    reverses_payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        primaryjoin="and_(Payment.shop_id == foreign(PaymentAllocation.shop_id), "
        "Payment.id == foreign(PaymentAllocation.payment_id))",
    )


class PaymentAllocation(Base):
    """Which open dues a collection settles. Negative rows reverse an earlier allocation."""

    __tablename__ = "payment_allocations"
    __table_args__ = (
        tenant_key(),
        tenant_fk("transaction_id", "business_transactions"),
        tenant_fk("payment_id", "payments"),
        tenant_fk("credit_entry_id", "credit_entries"),
        tenant_fk("reverses_allocation_id", "payment_allocations"),
        one_of("allocation_method", ("fifo_auto", "user_selected", "advance_auto", "reversal")),
        CheckConstraint("amount_paise <> 0", name="amount_nonzero"),
        CheckConstraint(
            "(amount_paise < 0) = (reverses_allocation_id IS NOT NULL)",
            name="negative_only_as_reversal",
        ),
        Index("ix_payment_allocations_shop_id_credit_entry_id", "shop_id", "credit_entry_id"),
        Index("ix_payment_allocations_shop_id_payment_id", "shop_id", "payment_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    credit_entry_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    amount_paise: Mapped[int] = paise()
    reverses_allocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    allocation_method: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
