"""Expense categories and expenses."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    PAYMENT_MODES,
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


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (
        tenant_key(),
        one_of("kind", ("business", "personal_withdrawal")),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 80", name="name_length"),
        Index(
            "uq_expense_categories_shop_id_lower_name_active",
            "shop_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_hi: Mapped[str | None] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="business")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        tenant_key(),
        tenant_fk("transaction_id", "business_transactions"),
        tenant_fk("category_id", "expense_categories"),
        UniqueConstraint("shop_id", "transaction_id"),
        one_of("mode", PAYMENT_MODES),
        one_of("status", ("active", "reversed")),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        Index("ix_expenses_shop_id_business_date", "shop_id", "business_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    amount_paise: Mapped[int] = paise()
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    payee: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
