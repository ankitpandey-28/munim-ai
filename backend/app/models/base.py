"""Declarative base and column/constraint helpers shared by every module's models.

Conventions (docs/physical-schema.md):
- UUIDv7 primary keys: generated in Python (``app.shared.ids.uuid7``) with ``DEFAULT uuidv7()``.
- Money: BIGINT paise, columns end in ``_paise``.
- Quantities: NUMERIC(14,3) in the product's base unit.
- Timestamps: ``timestamptz``; business dates: ``date`` in the shop's timezone.
- Enum-like values: ``text`` + CHECK constraint (no PostgreSQL ENUM types, easier to evolve).
- Tenant tables: ``shop_id NOT NULL`` + UNIQUE (shop_id, id) so children can reference
  (shop_id, parent_id) with composite foreign keys; cross-shop links become impossible.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Numeric,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.shared.ids import uuid7

# Deterministic constraint names keep Alembic migrations reviewable and reversible.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --------------------------------------------------------------------------- column helpers
def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid7, server_default=text("uuidv7()"))


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def shop_id_col() -> Mapped[uuid.UUID]:
    """Tenant column. Plain FK to shops; composite FKs on children enforce same-shop links."""
    return mapped_column(Uuid, ForeignKey("shops.id"), nullable=False, index=True)


def paise(nullable: bool = False, default: int | None = None) -> Mapped[int]:
    kwargs = {"server_default": text(str(default))} if default is not None else {}
    return mapped_column(BigInteger, nullable=nullable, **kwargs)


def quantity(nullable: bool = False) -> Mapped[Decimal]:
    return mapped_column(Numeric(14, 3), nullable=nullable)


# --------------------------------------------------------------------------- constraint helpers
def tenant_key() -> UniqueConstraint:
    """UNIQUE (shop_id, id): target of composite tenant foreign keys."""
    return UniqueConstraint("shop_id", "id")


def tenant_fk(
    column: str, target_table: str, *, name: str | None = None, use_alter: bool = False
) -> ForeignKeyConstraint:
    """(shop_id, column) -> target_table(shop_id, id): the referenced row must be in the same shop.

    ``use_alter`` breaks creation-order cycles (the constraint is added after both tables exist).
    """
    return ForeignKeyConstraint(
        ["shop_id", column],
        [f"{target_table}.shop_id", f"{target_table}.id"],
        name=name,
        use_alter=use_alter,
    )


def one_of(column: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name or f"{column}_valid")


# --------------------------------------------------------------------------- shared vocabularies
SOURCES = ("manual", "voice", "system")
PAYMENT_MODES = ("cash", "upi", "card", "other")
