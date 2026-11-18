"""Business transaction framework (database-design.md §5.1, architecture §8.4).

Every money/stock operation is posted as one ``business_transactions`` header; module services
write their child rows referencing it in the same DB transaction. A correction is a new header
of type ``reversal`` linked to the original; each module registers a *reversal handler* that
writes the exact negation of its child rows. Phase 2 provides the framework only; Phase 3
modules (sales, credit, inventory, expenses) register their handlers.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.request_context import get_request_id
from app.modules.audit import service as audit
from app.modules.ledger.models import TXN_TYPES, BusinessTransaction
from app.modules.shops.models import Shop

ReversalHandler = Callable[[Session, BusinessTransaction, BusinessTransaction], None]
_REVERSAL_HANDLERS: dict[str, ReversalHandler] = {}


class LedgerError(AppError):
    status_code = 422
    code = "LEDGER_RULE_VIOLATION"


def register_reversal_handler(txn_type: str, handler: ReversalHandler) -> None:
    """Register how to negate the child rows of ``txn_type``. Called once at import time by
    the owning module."""
    if txn_type not in TXN_TYPES or txn_type == "reversal":
        raise ValueError(f"cannot register a reversal handler for {txn_type!r}")
    _REVERSAL_HANDLERS[txn_type] = handler


def unregister_reversal_handler(txn_type: str) -> None:
    _REVERSAL_HANDLERS.pop(txn_type, None)


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    shop_id: uuid.UUID


@dataclass
class Approval:
    approved_by_user_id: uuid.UUID
    approval_request_id: uuid.UUID | None = None


@dataclass
class Override:
    override_type: str
    reason_code: str
    by_user_id: uuid.UUID
    note: str | None = None


@dataclass
class PostOptions:
    business_date: date | None = None
    occurred_at: datetime | None = None
    source: str = "manual"
    reason: str | None = None
    approval: Approval | None = None
    override: Override | None = None
    pending_action_id: uuid.UUID | None = None
    idempotency_key_id: uuid.UUID | None = None
    extra_audit: dict = field(default_factory=dict)


def shop_today(db: Session, shop_id: uuid.UUID, now: datetime | None = None) -> date:
    """Business date in the shop's timezone (SRS BR-TIME-01)."""
    tz_name = db.execute(select(Shop.timezone).where(Shop.id == shop_id)).scalar_one()
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(tz_name)).date()


def post_transaction(
    db: Session, actor: Actor, txn_type: str, options: PostOptions | None = None
) -> BusinessTransaction:
    """Create a posted header. The caller adds child rows and commits once."""
    if txn_type == "reversal":
        raise LedgerError("Use reverse_transaction() to post a reversal.")
    if txn_type not in TXN_TYPES:
        raise LedgerError(f"Unknown transaction type {txn_type!r}.")
    options = options or PostOptions()
    occurred_at = options.occurred_at or datetime.now(UTC)
    txn = BusinessTransaction(
        shop_id=actor.shop_id,
        txn_type=txn_type,
        status="posted",
        business_date=options.business_date or shop_today(db, actor.shop_id, occurred_at),
        occurred_at=occurred_at,
        initiated_by_user_id=actor.user_id,
        approved_by_user_id=options.approval.approved_by_user_id if options.approval else None,
        approval_request_id=options.approval.approval_request_id if options.approval else None,
        override_type=options.override.override_type if options.override else None,
        override_reason_code=options.override.reason_code if options.override else None,
        override_note=options.override.note if options.override else None,
        override_by_user_id=options.override.by_user_id if options.override else None,
        source=options.source,
        pending_action_id=options.pending_action_id,
        idempotency_key_id=options.idempotency_key_id,
        request_id=get_request_id(),
        reason=options.reason,
    )
    db.add(txn)
    db.flush()
    audit.record(
        db,
        action="ledger.transaction_posted",
        actor_user_id=actor.user_id,
        shop_id=actor.shop_id,
        entity_type="business_transaction",
        entity_id=txn.id,
        transaction_id=txn.id,
        source=options.source,
        after={"txn_type": txn_type, "business_date": txn.business_date, **options.extra_audit},
    )
    return txn


def reverse_transaction(
    db: Session,
    actor: Actor,
    original_id: uuid.UUID,
    *,
    reason: str,
    source: str = "manual",
) -> BusinessTransaction:
    """Post a linked reversal of ``original_id`` (at most once; reversals are not reversible).

    The original row is locked first, so concurrent reversals serialise; the unique index on
    ``reverses_transaction_id`` is the final guarantee.
    """
    if not reason or not reason.strip():
        raise LedgerError("A reason is required to reverse a transaction.")
    original = db.execute(
        select(BusinessTransaction)
        .where(BusinessTransaction.id == original_id, BusinessTransaction.shop_id == actor.shop_id)
        .with_for_update()
    ).scalar_one_or_none()
    if original is None:
        raise NotFound("Transaction not found.")
    if original.txn_type == "reversal":
        raise LedgerError("A reversal cannot itself be reversed; post a new transaction instead.")
    if original.status == "reversed":
        raise Conflict("This transaction has already been reversed.", code="ALREADY_REVERSED")
    handler = _REVERSAL_HANDLERS.get(original.txn_type)
    if handler is None:
        raise LedgerError(
            f"Reversal of {original.txn_type!r} transactions is not available yet.",
            code="REVERSAL_NOT_SUPPORTED",
        )
    now = datetime.now(UTC)
    reversal = BusinessTransaction(
        shop_id=actor.shop_id,
        txn_type="reversal",
        status="posted",
        reverses_transaction_id=original.id,
        business_date=shop_today(db, actor.shop_id, now),
        occurred_at=now,
        initiated_by_user_id=actor.user_id,
        source=source,
        request_id=get_request_id(),
        reason=reason.strip(),
    )
    db.add(reversal)
    db.flush()
    handler(db, original, reversal)
    original.status = "reversed"
    original.reversed_by_transaction_id = reversal.id
    db.flush()
    audit.record(
        db,
        action="ledger.transaction_reversed",
        actor_user_id=actor.user_id,
        shop_id=actor.shop_id,
        entity_type="business_transaction",
        entity_id=original.id,
        transaction_id=reversal.id,
        source=source,
        before={"status": "posted"},
        after={"status": "reversed", "reversed_by": reversal.id, "reason": reason.strip()},
    )
    return reversal
