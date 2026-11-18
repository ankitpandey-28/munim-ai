"""Idempotency keys (SRS BR-DUP-01, architecture §8.5).

Protocol, all inside ONE database transaction with the business operation:

1. ``claim()``: INSERT the key row with ON CONFLICT DO NOTHING.
   - If another request with the same key is still running, PostgreSQL blocks this INSERT on
     the unique index until that transaction ends. If it committed, this INSERT does nothing and
     we read the committed row; if it rolled back, this INSERT succeeds and we run normally.
   - So a visible row is always a *completed* request: duplicates replay its stored response.
2. The business operation runs.
3. ``complete()``: store the response on the claimed row; the caller then commits once.

A different request body under the same key is rejected (409), never replayed.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.platform.models import IdempotencyKey
from app.shared.ids import uuid7

IDEMPOTENCY_HEADER = "Idempotency-Key"
KEY_TTL = timedelta(hours=48)


class IdempotencyKeyMissing(AppError):
    status_code = 400
    code = "IDEMPOTENCY_KEY_REQUIRED"


def fingerprint(method: str, path: str, body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{method.upper()} {path}\n{canonical}".encode()).hexdigest()


def validate_key(key: str | None) -> str:
    if key is None or not (8 <= len(key.strip()) <= 128):
        raise IdempotencyKeyMissing(
            f"Send a unique {IDEMPOTENCY_HEADER} header (8-128 characters) with this request."
        )
    return key.strip()


@dataclass
class Claim:
    row_id: uuid.UUID
    replay: bool
    response_status: int | None = None
    response_body: Any = None


def claim(
    db: Session,
    *,
    user_id: uuid.UUID,
    shop_id: uuid.UUID | None,
    key: str,
    request_fingerprint: str,
) -> Claim:
    now = datetime.now(UTC)
    new_id = uuid7()
    stmt = insert(IdempotencyKey).values(
        id=new_id,
        shop_id=shop_id,
        user_id=user_id,
        key=key,
        request_fingerprint=request_fingerprint,
        created_at=now,
        expires_at=now + KEY_TTL,
    )
    if shop_id is None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["user_id", "key"], index_where=IdempotencyKey.shop_id.is_(None)
        )
    else:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["shop_id", "user_id", "key"],
            index_where=IdempotencyKey.shop_id.is_not(None),
        )
    inserted = db.execute(stmt.returning(IdempotencyKey.id)).scalar_one_or_none()
    if inserted is not None:
        return Claim(row_id=inserted, replay=False)

    query = select(IdempotencyKey).where(
        IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
    )
    query = query.where(
        IdempotencyKey.shop_id.is_(None) if shop_id is None else IdempotencyKey.shop_id == shop_id
    )
    existing = db.execute(query).scalar_one()
    if existing.request_fingerprint != request_fingerprint:
        raise Conflict(
            "This Idempotency-Key was already used for a different request.",
            code="IDEMPOTENCY_KEY_REUSED",
        )
    return Claim(
        row_id=existing.id,
        replay=True,
        response_status=existing.response_status,
        response_body=existing.response_body,
    )


def complete(
    db: Session,
    claimed: Claim,
    *,
    response_status: int,
    response_body: Any,
    transaction_id: uuid.UUID | None = None,
) -> None:
    row = db.get(IdempotencyKey, claimed.row_id)
    if row is None:  # pragma: no cover - the row was inserted in this transaction
        raise RuntimeError("idempotency claim disappeared")
    row.response_status = response_status
    row.response_body = json.loads(json.dumps(response_body, default=str))
    row.transaction_id = transaction_id
    row.completed_at = datetime.now(UTC)
