"""Inventory endpoints: /api/v1/inventory/*

HTTP only: schemas validate input, permission dependencies gate access, one commit per request.
Business rules, locking, valuation and cost hiding live in ``app.modules.inventory.service``.
The shop is always the session's verified active shop; no endpoint accepts a shop id.
Every write is idempotent (``Idempotency-Key`` header): a retried request replays the original
response and never posts stock twice.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import DbSession, require
from app.api.idempotent import run_idempotent
from app.modules.inventory import service
from app.modules.inventory.schemas import (
    AdjustmentCreate,
    GoodsReceiptCreate,
    InventorySummary,
    InventoryTransactionResult,
    MovementListResponse,
    OpeningStockCreate,
    ReversalCreate,
    StockCountCreate,
    StockItem,
    StockListResponse,
    StockStatus,
)
from app.modules.shops.context import ShopContext
from app.modules.shops.permissions import Permission

router = APIRouter(prefix="/inventory", tags=["inventory"])

CanView = Annotated[ShopContext, Depends(require(Permission.INVENTORY_VIEW))]
CanReceive = Annotated[ShopContext, Depends(require(Permission.INVENTORY_RECEIVE))]
CanAdjust = Annotated[ShopContext, Depends(require(Permission.INVENTORY_ADJUST))]

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


def _write(request: Request, db, ctx: ShopContext, body, operation) -> object:
    def run():
        result = operation()
        return result, result.transaction_id

    return run_idempotent(
        db, request, user_id=ctx.user_id, shop_id=ctx.shop_id, payload=body,
        status_code=status.HTTP_201_CREATED, operation=run,
    )  # fmt: skip


# ----------------------------------------------------------------------------- reads
@router.get("/summary", response_model=InventorySummary, summary="Stock overview")
def get_summary(db: DbSession, ctx: CanView) -> InventorySummary:
    return service.summary(db, ctx)


@router.get("/stock", response_model=StockListResponse, summary="Tracked products with stock")
def list_stock(
    db: DbSession,
    ctx: CanView,
    q: Annotated[str | None, Query(max_length=120)] = None,
    category_id: uuid.UUID | None = None,
    stock_status: Annotated[StockStatus, Query(alias="status")] = "all",
    limit: Limit = 50,
    offset: Offset = 0,
) -> StockListResponse:
    return service.list_stock(
        db, ctx, q=q, category_id=category_id, status=stock_status, limit=limit, offset=offset
    )


@router.get("/stock/{product_id}", response_model=StockItem, summary="Stock of one product")
def get_stock(product_id: uuid.UUID, db: DbSession, ctx: CanView) -> StockItem:
    return service.get_stock(db, ctx, product_id)


@router.get("/movements", response_model=MovementListResponse, summary="Stock movement history")
def list_movements(
    db: DbSession,
    ctx: CanView,
    product_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> MovementListResponse:
    return service.list_movements(db, ctx, product_id=product_id, limit=limit, offset=offset)


# ----------------------------------------------------------------------------- writes
@router.post(
    "/opening-stock",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryTransactionResult,
    summary="Record opening stock (owner/admin). Idempotent.",
)
def opening_stock(body: OpeningStockCreate, request: Request, db: DbSession, ctx: CanAdjust):
    return _write(request, db, ctx, body, lambda: service.record_opening_stock(db, ctx, body))


@router.post(
    "/receipts",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryTransactionResult,
    summary="Record goods received. Idempotent.",
)
def receipts(body: GoodsReceiptCreate, request: Request, db: DbSession, ctx: CanReceive):
    return _write(request, db, ctx, body, lambda: service.receive_goods(db, ctx, body))


@router.post(
    "/adjustments",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryTransactionResult,
    summary="Reduce stock for damage, expiry or loss (owner/admin). Idempotent.",
)
def adjustments(body: AdjustmentCreate, request: Request, db: DbSession, ctx: CanAdjust):
    return _write(request, db, ctx, body, lambda: service.adjust_stock(db, ctx, body))


@router.post(
    "/counts",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryTransactionResult,
    summary="Post a physical stock count (owner/admin). Idempotent.",
)
def counts(body: StockCountCreate, request: Request, db: DbSession, ctx: CanAdjust):
    return _write(request, db, ctx, body, lambda: service.post_count(db, ctx, body))


@router.post(
    "/transactions/{transaction_id}/reverse",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryTransactionResult,
    summary="Reverse a stock transaction with a reason (owner/admin). Idempotent.",
)
def reverse(
    transaction_id: uuid.UUID,
    body: ReversalCreate,
    request: Request,
    db: DbSession,
    ctx: CanAdjust,
):
    return _write(request, db, ctx, body, lambda: service.reverse(db, ctx, transaction_id, body))
