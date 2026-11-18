"""Inventory: cached levels, append-only stock movements, physical counts."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    created_at_col,
    one_of,
    paise,
    quantity,
    shop_id_col,
    tenant_fk,
    tenant_key,
    updated_at_col,
    uuid_pk,
)

MOVEMENT_TYPES = (
    "opening",
    "sale",
    "sale_reversal",
    "purchase_receipt",
    "purchase_reversal",
    "adjustment_damage",
    "adjustment_expiry",
    "adjustment_loss",
    "adjustment_count",
    "return_to_supplier",
)


class InventoryLevel(Base):
    """Cached projection of stock_movements (+ weighted-average cost). Reconciled nightly."""

    __tablename__ = "inventory_levels"
    __table_args__ = (
        tenant_fk("product_id", "products"),
        CheckConstraint(
            "avg_cost_paise IS NULL OR avg_cost_paise >= 0", name="avg_cost_nonnegative"
        ),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("shops.id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # May be negative only as the result of a recorded owner override (invariant I11).
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )
    avg_cost_paise: Mapped[int | None] = paise(nullable=True)
    last_movement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = updated_at_col()


class StockMovement(Base):
    """Append-only. Corrections are reversal rows in a reversal business transaction."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        tenant_key(),
        tenant_fk("transaction_id", "business_transactions"),
        tenant_fk("product_id", "products"),
        tenant_fk("reverses_movement_id", "stock_movements"),
        one_of("movement_type", MOVEMENT_TYPES),
        CheckConstraint("quantity_delta <> 0", name="quantity_delta_nonzero"),
        CheckConstraint(
            "unit_cost_paise IS NULL OR unit_cost_paise >= 0", name="unit_cost_nonnegative"
        ),
        Index(
            "ix_stock_movements_shop_id_product_id_occurred_at",
            "shop_id",
            "product_id",
            "occurred_at",
        ),
        Index("ix_stock_movements_shop_id_transaction_id", "shop_id", "transaction_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity_delta: Mapped[Decimal] = quantity()
    unit_cost_paise: Mapped[int | None] = paise(nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reverses_movement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quantity_on_hand_after: Mapped[Decimal] = quantity()
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class StockCount(Base):
    __tablename__ = "stock_counts"
    __table_args__ = (
        tenant_key(),
        tenant_fk("posted_transaction_id", "business_transactions"),
        one_of("status", ("draft", "posted", "cancelled")),
        CheckConstraint(
            "(status = 'posted') = (posted_transaction_id IS NOT NULL)",
            name="posted_has_transaction",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="draft")
    started_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    posted_transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    notes: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    items: Mapped[list["StockCountItem"]] = relationship(
        primaryjoin="and_(StockCount.shop_id == foreign(StockCountItem.shop_id), "
        "StockCount.id == foreign(StockCountItem.stock_count_id))",
    )


class StockCountItem(Base):
    __tablename__ = "stock_count_items"
    __table_args__ = (
        tenant_key(),
        tenant_fk("stock_count_id", "stock_counts"),
        tenant_fk("product_id", "products"),
        UniqueConstraint("shop_id", "stock_count_id", "product_id"),
        CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0", name="counted_nonnegative"
        ),
        CheckConstraint(
            "difference IS NULL OR difference = counted_quantity - system_quantity",
            name="difference_consistent",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    stock_count_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    system_quantity: Mapped[Decimal] = quantity()
    counted_quantity: Mapped[Decimal | None] = quantity(nullable=True)
    difference: Mapped[Decimal | None] = quantity(nullable=True)
    reason: Mapped[str | None] = mapped_column(String(120))
