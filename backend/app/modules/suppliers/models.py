"""Suppliers and the products they usually supply."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    created_at_col,
    paise,
    quantity,
    shop_id_col,
    tenant_fk,
    tenant_key,
    updated_at_col,
    uuid_pk,
)


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        tenant_key(),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("phone IS NULL OR phone ~ '^\\+91[6-9][0-9]{9}$'", name="phone_e164_in"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class SupplierProduct(Base):
    __tablename__ = "supplier_products"
    __table_args__ = (
        tenant_key(),
        tenant_fk("supplier_id", "suppliers"),
        tenant_fk("product_id", "products"),
        UniqueConstraint("shop_id", "supplier_id", "product_id"),
        CheckConstraint(
            "last_cost_paise IS NULL OR last_cost_paise >= 0", name="last_cost_nonnegative"
        ),
        CheckConstraint("pack_size IS NULL OR pack_size > 0", name="pack_size_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    is_preferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_cost_paise: Mapped[int | None] = paise(nullable=True)
    pack_size: Mapped[Decimal | None] = quantity(nullable=True)
    pack_unit_code: Mapped[str | None] = mapped_column(String(16), ForeignKey("units.code"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
