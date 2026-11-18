"""Catalog: units (global reference), categories, products, aliases, price history."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    SOURCES,
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


class Unit(Base):
    """Global reference data (seeded by migration). Read-only for the runtime role."""

    __tablename__ = "units"
    __table_args__ = (
        one_of("dimension", ("mass", "volume", "count")),
        CheckConstraint("factor_to_dimension_base > 0", name="factor_positive"),
    )

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(8), nullable=False)
    # e.g. g -> 0.001 (kg), ml -> 0.001 (l), dozen -> 12 (piece)
    factor_to_dimension_base: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    allows_decimal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    name_en: Mapped[str] = mapped_column(String(40), nullable=False)
    name_hi: Mapped[str] = mapped_column(String(40), nullable=False)
    spoken_forms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )


class ProductCategory(Base):
    __tablename__ = "product_categories"
    __table_args__ = (
        tenant_key(),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 80", name="name_length"),
        Index(
            "uq_product_categories_shop_id_lower_name_active",
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
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        tenant_key(),
        tenant_fk("category_id", "product_categories"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("selling_price_paise >= 0", name="selling_price_nonnegative"),
        CheckConstraint(
            "default_cost_price_paise IS NULL OR default_cost_price_paise >= 0",
            name="default_cost_nonnegative",
        ),
        CheckConstraint(
            "reorder_level IS NULL OR reorder_level >= 0", name="reorder_level_nonnegative"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "uq_products_shop_id_lower_name_active",
            "shop_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "uq_products_shop_id_barcode",
            "shop_id",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_hi: Mapped[str | None] = mapped_column(String(120))
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    base_unit_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("units.code"), nullable=False
    )
    is_loose: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    selling_price_paise: Mapped[int] = paise()
    default_cost_price_paise: Mapped[int | None] = paise(nullable=True)
    reorder_level: Mapped[Decimal | None] = quantity(nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    aliases: Mapped[list["ProductAlias"]] = relationship(
        primaryjoin="and_(Product.shop_id == foreign(ProductAlias.shop_id), "
        "Product.id == foreign(ProductAlias.product_id))",
        back_populates="product",
    )


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        tenant_key(),
        tenant_fk("product_id", "products"),
        UniqueConstraint("shop_id", "product_id", "normalized_text"),
        one_of("source", ("seed", "manual", "learned")),
        CheckConstraint("length(trim(alias_text)) BETWEEN 1 AND 120", name="alias_length"),
        Index(
            "ix_product_aliases_normalized_text_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    alias_text: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(120), nullable=False)
    phonetic_key: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual")
    created_at: Mapped[datetime] = created_at_col()

    product: Mapped[Product] = relationship(
        primaryjoin="and_(Product.shop_id == foreign(ProductAlias.shop_id), "
        "Product.id == foreign(ProductAlias.product_id))",
        back_populates="aliases",
    )


class ProductPrice(Base):
    __tablename__ = "product_prices"
    __table_args__ = (
        tenant_key(),
        tenant_fk("product_id", "products"),
        one_of("price_type", ("selling", "cost")),
        one_of("source", SOURCES),
        CheckConstraint("price_paise >= 0", name="price_nonnegative"),
        Index(
            "ix_product_prices_shop_id_product_id_effective_from",
            "shop_id",
            "product_id",
            "effective_from",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    price_type: Mapped[str] = mapped_column(String(8), nullable=False)
    price_paise: Mapped[int] = paise()
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    set_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="manual")
    created_at: Mapped[datetime] = created_at_col()
