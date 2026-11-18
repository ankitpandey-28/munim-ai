"""Audit trail writer. Always called inside the same DB transaction as the change it records."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import REDACTED, is_sensitive_key
from app.core.request_context import get_request_id
from app.modules.audit.models import AuditLog

# Keys that must never be stored in before/after snapshots (in addition to logging's list).
_EXTRA_SENSITIVE = ("hash", "token", "secret", "password")


def _sanitize(value: Any, key: str = "") -> Any:
    if key and (is_sensitive_key(key) or any(p in key.lower() for p in _EXTRA_SENSITIVE)):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): _sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_sanitize(v, key) for v in value]
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return REDACTED
    return value


def record(
    db: Session,
    *,
    action: str,
    actor_user_id: uuid.UUID | None,
    shop_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    source: str = "manual",
    transaction_id: uuid.UUID | None = None,
    pending_action_id: uuid.UUID | None = None,
    approval_request_id: uuid.UUID | None = None,
    ip_hash: str | None = None,
    actor_type: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        shop_id=shop_id,
        actor_user_id=actor_user_id,
        actor_type=actor_type or ("user" if actor_user_id else "anonymous"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=_sanitize(before) if before is not None else None,
        after=_sanitize(after) if after is not None else None,
        source=source,
        transaction_id=transaction_id,
        pending_action_id=pending_action_id,
        approval_request_id=approval_request_id,
        request_id=get_request_id(),
        ip_hash=ip_hash,
    )
    db.add(entry)
    return entry
