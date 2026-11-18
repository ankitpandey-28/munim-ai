"""Sales (revenue records). Money received lives in ``payments``; credit portions in
``credit_entries`` (database-design.md §5.2)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
from app.models.base import (
    quantity as qty_col,
)


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        tenant_key(),
        tenant_fk("transaction_id", "business_transactions"),
        tenant_fk("customer_id", "customers"),
        UniqueConstraint("shop_id", "transaction_id"),
        UniqueConstraint("shop_id", "sale_number"),
        one_of("sale_type", ("itemized", "unitemized")),
        one_of("status", ("active", "reversed")),
        CheckConstraint("sale_number > 0", name="sale_number_positive"),
        CheckConstraint(
            "subtotal_paise >= 0 AND discount_paise >= 0"
            " AND paid_now_paise >= 0 AND credit_paise >= 0",
            name="amounts_nonnegative",
        ),
        CheckConstraint("total_paise > 0", name="total_positive"),
        CheckConstraint(
            "total_paise = subtotal_paise - discount_paise", name="total_is_subtotal_minus_discount"
        ),
        CheckConstraint(
            "total_paise = paid_now_paise + credit_paise", name="total_is_paid_plus_credit"
        ),
        CheckConstraint(
            "credit_paise = 0 OR customer_id IS NOT NULL", name="credit_requires_customer"
        ),
        Index("ix_sales_shop_id_business_date", "shop_id", "business_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    sale_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sale_type: Mapped[str] = mapped_column(String(12), nullable=False)
    subtotal_paise: Mapped[int] = paise()
    discount_paise: Mapped[int] = paise(default=0)
    total_paise: Mapped[int] = paise()
    paid_now_paise: Mapped[int] = paise()
    credit_paise: Mapped[int] = paise(default=0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    items: Mapped[list["SaleItem"]] = relationship(
        primaryjoin="and_(Sale.shop_id == foreign(SaleItem.shop_id), "
        "Sale.id == foreign(SaleItem.sale_id))",
    )


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        tenant_key(),
        tenant_fk("sale_id", "sales"),
        tenant_fk("product_id", "products"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("entered_quantity > 0", name="entered_quantity_positive"),
        CheckConstraint(
            "unit_price_paise >= 0 AND line_discount_paise >= 0 AND line_total_paise >= 0",
            name="amounts_nonnegative",
        ),
        CheckConstraint(
            "cost_known = (unit_cost_paise IS NOT NULL AND line_cost_paise IS NOT NULL)",
            name="cost_known_consistent",
        ),
        CheckConstraint(
            "(unit_cost_paise IS NULL OR unit_cost_paise >= 0)"
            " AND (line_cost_paise IS NULL OR line_cost_paise >= 0)",
            name="costs_nonnegative",
        ),
        Index("ix_sale_items_shop_id_sale_id", "shop_id", "sale_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    sale_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[Decimal] = qty_col()
    entered_quantity: Mapped[Decimal] = qty_col()
    entered_unit_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("units.code"), nullable=False
    )
    unit_price_paise: Mapped[int] = paise()
    line_discount_paise: Mapped[int] = paise(default=0)
    line_total_paise: Mapped[int] = paise()
    unit_cost_paise: Mapped[int | None] = paise(nullable=True)
    cost_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    line_cost_paise: Mapped[int | None] = paise(nullable=True)
