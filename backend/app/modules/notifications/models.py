"""WhatsApp reminder-link records and in-app notifications."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    created_at_col,
    one_of,
    paise,
    shop_id_col,
    tenant_fk,
    tenant_key,
    uuid_pk,
)


class Reminder(Base):
    """A generated wa.me reminder link. The URL itself (phone + amount) is never stored."""

    __tablename__ = "reminders"
    __table_args__ = (
        tenant_key(),
        tenant_fk("customer_id", "customers"),
        tenant_fk("pending_action_id", "pending_actions"),
        one_of("channel", ("whatsapp_link",)),
        one_of("status", ("generated", "opened", "marked_sent", "cancelled")),
        Index(
            "ix_reminders_shop_id_customer_id_generated_at",
            "shop_id",
            "customer_id",
            "generated_at",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, server_default="whatsapp_link")
    template_code: Mapped[str] = mapped_column(String(48), nullable=False)
    balance_at_generation_paise: Mapped[int] = paise()
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="generated")
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    generated_at: Mapped[datetime] = created_at_col()
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marked_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        tenant_key(),
        Index(
            "ix_notifications_shop_id_user_id_unread",
            "shop_id",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shop_id: Mapped[uuid.UUID] = shop_id_col()
    # NULL = addressed to all owners of the shop.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
