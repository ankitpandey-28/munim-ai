"""Run a write endpoint idempotently: claim key -> operation -> store response -> one commit."""

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.modules.platform import idempotency

REPLAY_HEADER = "Idempotent-Replayed"


def run_idempotent(
    db: Session,
    request: Request,
    *,
    user_id: uuid.UUID,
    shop_id: uuid.UUID | None,
    payload: BaseModel | None,
    status_code: int,
    operation: Callable[[], tuple[Any, uuid.UUID | None]],
    on_success: Callable[[JSONResponse], None] | None = None,
) -> JSONResponse:
    key = idempotency.validate_key(request.headers.get(idempotency.IDEMPOTENCY_HEADER))
    body = payload.model_dump(mode="json") if payload is not None else None
    fp = idempotency.fingerprint(request.method, request.url.path, body)
    claimed = idempotency.claim(
        db, user_id=user_id, shop_id=shop_id, key=key, request_fingerprint=fp
    )
    if claimed.replay:
        db.rollback()
        return JSONResponse(
            content=claimed.response_body,
            status_code=claimed.response_status or 200,
            headers={REPLAY_HEADER: "true"},
        )
    result, transaction_id = operation()
    content = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
    idempotency.complete(
        db,
        claimed,
        response_status=status_code,
        response_body=content,
        transaction_id=transaction_id,
    )
    db.commit()
    response = JSONResponse(content=content, status_code=status_code)
    if on_success is not None:
        on_success(response)
    return response
