"""Customers and their nicknames/aliases."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
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
    paise,
    shop_id_col,
    tenant_fk,
    tenant_key,
    updated_at_col,
    uuid_pk,
)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        tenant_key(),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("phone IS NULL OR phone ~ '^\\+91[6-9][0-9]{9}$'", name="phone_e164_in"),
        CheckConstraint(
            "credit_limit_paise IS NULL OR credit_limit_paise >= 0", name="credit_limit_nonnegative"
        ),
        CheckConstraint(
            "(NOT reminder_consent) OR consent_at IS NOT NULL", name="consent_has_timestamp"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "uq_customers_shop_id_phone",
            "shop_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
        Index(
            "ix_customers_name_normalized_trgm",
            "name_normalized",
            postgresql_using="gin",
            postgresql_ops={"name_normalized": "gin_trgm_ops"},
        ),
        Index(
            "ix_customers_shop_id_balance_positive",
            "shop_id",
            "balance_paise",
            postgresql_where=text("balance_paise > 0"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(120), nullable=False)
    phonetic_key: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(16))
    landmark: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    reminder_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_source: Mapped[str | None] = mapped_column(String(32))
    credit_limit_paise: Mapped[int | None] = paise(nullable=True)
    # Cached: + customer owes the shop, - advance held. Invariant I2: = SUM(credit_entries).
    balance_paise: Mapped[int] = paise(default=0)
    oldest_open_credit_date: Mapped[date | None] = mapped_column(Date)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    aliases: Mapped[list["CustomerAlias"]] = relationship(
        primaryjoin="and_(Customer.shop_id == foreign(CustomerAlias.shop_id), "
        "Customer.id == foreign(CustomerAlias.customer_id))",
    )


class CustomerAlias(Base):
    __tablename__ = "customer_aliases"
    __table_args__ = (
        tenant_key(),
        tenant_fk("customer_id", "customers"),
        UniqueConstraint("shop_id", "customer_id", "normalized_text"),
        CheckConstraint("length(trim(alias_text)) BETWEEN 1 AND 120", name="alias_length"),
        Index(
            "ix_customer_aliases_normalized_text_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    alias_text: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(120), nullable=False)
    phonetic_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_col()
