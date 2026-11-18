"""Purchase orders (no stock/money effect) and goods receipts (stock + cost effect)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    SOURCES,
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


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        tenant_key(),
        tenant_fk("supplier_id", "suppliers"),
        tenant_fk("pending_action_id", "pending_actions"),
        UniqueConstraint("shop_id", "po_number"),
        one_of("status", ("draft", "sent", "partially_received", "received", "cancelled")),
        one_of("source", SOURCES),
        CheckConstraint("po_number > 0", name="po_number_positive"),
        CheckConstraint(
            "estimated_total_paise IS NULL OR estimated_total_paise >= 0",
            name="estimate_nonnegative",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_purchase_orders_shop_id_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    po_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    estimated_total_paise: Mapped[int | None] = paise(nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="manual")
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        primaryjoin="and_(PurchaseOrder.shop_id == foreign(PurchaseOrderItem.shop_id), "
        "PurchaseOrder.id == foreign(PurchaseOrderItem.purchase_order_id))",
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        tenant_key(),
        tenant_fk("purchase_order_id", "purchase_orders"),
        tenant_fk("product_id", "products"),
        CheckConstraint("ordered_quantity > 0", name="ordered_quantity_positive"),
        CheckConstraint("received_quantity >= 0", name="received_quantity_nonnegative"),
        CheckConstraint(
            "expected_unit_cost_paise IS NULL OR expected_unit_cost_paise >= 0",
            name="expected_cost_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ordered_quantity: Mapped[Decimal] = qty_col()
    unit_code: Mapped[str] = mapped_column(String(16), ForeignKey("units.code"), nullable=False)
    expected_unit_cost_paise: Mapped[int | None] = paise(nullable=True)
    # Cached sum of goods_receipt_items for this line.
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )


class GoodsReceipt(Base):
    """Stock-in event. 1-1 with a business transaction of type goods_receipt."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        tenant_key(),
        tenant_fk("transaction_id", "business_transactions"),
        tenant_fk("supplier_id", "suppliers"),
        tenant_fk("purchase_order_id", "purchase_orders"),
        UniqueConstraint("shop_id", "transaction_id"),
        CheckConstraint("total_cost_paise >= 0", name="total_cost_nonnegative"),
        Index("ix_goods_receipts_shop_id_received_at", "shop_id", "received_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    invoice_number: Mapped[str | None] = mapped_column(String(64))
    total_cost_paise: Mapped[int] = paise()
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    items: Mapped[list["GoodsReceiptItem"]] = relationship(
        primaryjoin="and_(GoodsReceipt.shop_id == foreign(GoodsReceiptItem.shop_id), "
        "GoodsReceipt.id == foreign(GoodsReceiptItem.goods_receipt_id))",
    )


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = (
        tenant_key(),
        tenant_fk("goods_receipt_id", "goods_receipts"),
        tenant_fk("product_id", "products"),
        tenant_fk("purchase_order_item_id", "purchase_order_items"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "unit_cost_paise >= 0 AND line_total_paise >= 0", name="amounts_nonnegative"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    purchase_order_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    quantity: Mapped[Decimal] = qty_col()
    unit_cost_paise: Mapped[int] = paise()
    line_total_paise: Mapped[int] = paise()
