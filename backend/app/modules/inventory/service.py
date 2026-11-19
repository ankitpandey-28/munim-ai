"""Inventory business logic: opening stock, goods receipts, adjustments, counts, reversals,
stock levels, movement history and valuation (SRS FR-INV-01..06, database-design §4.3).

Rules (decision log D-05, D-08, D-11, D-12):
- Every stock change is an immutable ``stock_movements`` row inside a business transaction;
  ``inventory_levels`` is the cached projection, updated in the same DB transaction.
- Untracked products (``track_stock = false``) never get movements; archived products cannot
  receive new stock operations (reversals of past ones are still allowed).
- Stock never goes negative here: no override exists for these operations (sales overrides
  arrive with Phase 6).
- Weighted-average cost changes only on inflows with a known cost (receipt, opening with cost)
  and when such an inflow is reversed (backed out at its cost, D-11). Outflows and their
  reversals carry the average as a snapshot and leave it unchanged.
- Locking: product rows FOR SHARE (serialises with catalogue edits, which lock FOR UPDATE),
  then inventory levels FOR UPDATE, both in product-id order so concurrent requests cannot
  deadlock or lose updates.
- Costs and stock value are returned only to callers with ``inventory.view_value``.
- Functions never commit; the API layer commits once per request (with idempotency).
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import Conflict, InvalidInput, NotFound, PermissionDenied
from app.modules.catalog.models import Product
from app.modules.identity.models import User
from app.modules.inventory.models import (
    InventoryLevel,
    StockCount,
    StockCountItem,
    StockMovement,
)
from app.modules.inventory.schemas import (
    AdjustmentCreate,
    GoodsReceiptCreate,
    InventorySummary,
    InventoryTransactionResult,
    MovementListResponse,
    MovementRead,
    OpeningStockCreate,
    ReversalCreate,
    StockCountCreate,
    StockItem,
    StockListResponse,
    StockStatus,
)
from app.modules.ledger import service as ledger
from app.modules.ledger.models import BusinessTransaction
from app.modules.purchasing.models import GoodsReceipt, GoodsReceiptItem
from app.modules.shops.context import ShopContext
from app.modules.shops.permissions import Permission, has_permission
from app.modules.suppliers.models import Supplier

ZERO = Decimal("0.000")
INVENTORY_TXN_TYPES = ("opening_balance", "goods_receipt", "stock_adjustment", "stock_count")
INFLOW_WITH_COST = ("opening", "purchase_receipt")


# ----------------------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now(UTC)


def _require(ctx: ShopContext, permission: Permission) -> None:
    if not has_permission(ctx.role, permission):
        raise PermissionDenied("You do not have permission to do this in this shop.")


def can_view_value(ctx: ShopContext) -> bool:
    return has_permission(ctx.role, Permission.INVENTORY_VIEW_VALUE)


def round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def receipt_average(
    on_hand: Decimal, avg: int | None, default_cost: int | None, qty: Decimal, cost: int
) -> int:
    """Weighted average after an inflow of ``qty`` at ``cost`` (database-design §4.3).

    On-hand is floored at 0 when negative. Existing stock with no known cost is valued at the
    product's default cost (D-05); with neither, the new cost is the only information (D-12f).
    """
    basis_qty = max(on_hand, ZERO)
    basis_cost = avg if avg is not None else default_cost
    if basis_qty == 0 or basis_cost is None:
        return cost
    return round_half_up((basis_qty * basis_cost + qty * cost) / (basis_qty + qty))


def backout_average(on_hand: Decimal, avg: int | None, qty: Decimal, cost: int) -> int | None:
    """Average after reversing an inflow of ``qty`` at ``cost`` (D-11). Caller guarantees
    ``on_hand >= qty``. Kept when nothing remains or the average is unknown; floored at 0."""
    remaining = on_hand - qty
    if remaining == 0 or avg is None:
        return avg
    return max(0, round_half_up((on_hand * avg - qty * cost) / remaining))


def _insufficient(product: Product, available: Decimal, requested: Decimal) -> Conflict:
    return Conflict(
        f"Not enough stock of {product.name}: {available} {product.base_unit_code} available.",
        code="INSUFFICIENT_STOCK",
        details={
            "product_id": str(product.id),
            "available": str(available),
            "requested": str(requested),
        },
    )


def _lock_products(
    db: Session, ctx: ShopContext, product_ids: Iterable[uuid.UUID], *, for_new_stock: bool
) -> dict[uuid.UUID, Product]:
    ids = sorted(set(product_ids))
    rows = db.scalars(
        select(Product)
        .where(Product.shop_id == ctx.shop_id, Product.id.in_(ids))
        .order_by(Product.id)
        .with_for_update(read=True)
    ).all()
    products = {p.id: p for p in rows}
    if len(products) != len(ids):
        raise NotFound("Product not found.")
    for p in rows:
        if not p.track_stock:
            raise Conflict(
                f"Stock is not tracked for {p.name}. Turn on stock tracking first.",
                code="STOCK_NOT_TRACKED",
                details={"product_id": str(p.id)},
            )
        if for_new_stock and p.archived_at is not None:
            raise Conflict(f"{p.name} is archived.", code="PRODUCT_ARCHIVED")
    return products


def _lock_levels(
    db: Session, ctx: ShopContext, product_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, InventoryLevel]:
    ids = sorted(set(product_ids))
    db.execute(
        pg_insert(InventoryLevel)
        .values([{"shop_id": ctx.shop_id, "product_id": pid} for pid in ids])
        .on_conflict_do_nothing(index_elements=["shop_id", "product_id"])
    )
    rows = db.scalars(
        select(InventoryLevel)
        .where(InventoryLevel.shop_id == ctx.shop_id, InventoryLevel.product_id.in_(ids))
        .order_by(InventoryLevel.product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return {lvl.product_id: lvl for lvl in rows}


def _move(
    db: Session,
    level: InventoryLevel,
    *,
    txn: BusinessTransaction,
    movement_type: str,
    delta: Decimal,
    unit_cost_paise: int | None,
    occurred_at: datetime,
    reference: tuple[str, uuid.UUID] | None = None,
    reverses: uuid.UUID | None = None,
) -> StockMovement:
    after = level.quantity_on_hand + delta
    movement = StockMovement(
        id=uuid.uuid4(),
        shop_id=level.shop_id,
        transaction_id=txn.id,
        product_id=level.product_id,
        movement_type=movement_type,
        quantity_delta=delta,
        unit_cost_paise=unit_cost_paise,
        reference_type=reference[0] if reference else None,
        reference_id=reference[1] if reference else None,
        reverses_movement_id=reverses,
        quantity_on_hand_after=after,
        occurred_at=occurred_at,
    )
    db.add(movement)
    level.quantity_on_hand = after
    level.last_movement_id = movement.id
    level.updated_at = occurred_at
    return movement


def _snapshot_cost(level: InventoryLevel, product: Product) -> int | None:
    return (
        level.avg_cost_paise
        if level.avg_cost_paise is not None
        else (product.default_cost_price_paise)
    )


def _actor(ctx: ShopContext) -> ledger.Actor:
    return ledger.Actor(user_id=ctx.user_id, shop_id=ctx.shop_id)


# ----------------------------------------------------------------------------- reads
def _movement_query() -> Select:
    return (
        select(
            StockMovement,
            BusinessTransaction.txn_type,
            BusinessTransaction.status,
            BusinessTransaction.reason,
            Product.name,
            Product.base_unit_code,
            User.name,
        )
        .join(
            BusinessTransaction,
            and_(
                BusinessTransaction.shop_id == StockMovement.shop_id,
                BusinessTransaction.id == StockMovement.transaction_id,
            ),
        )
        .join(
            Product,
            and_(Product.shop_id == StockMovement.shop_id, Product.id == StockMovement.product_id),
        )
        .outerjoin(User, User.id == BusinessTransaction.initiated_by_user_id)
    )


def _movement_reads(ctx: ShopContext, rows: Sequence) -> list[MovementRead]:
    show = can_view_value(ctx)
    return [
        MovementRead(
            id=m.id,
            transaction_id=m.transaction_id,
            txn_type=txn_type,
            txn_status=status,
            product_id=m.product_id,
            product_name=pname,
            base_unit_code=unit,
            movement_type=m.movement_type,
            quantity_delta=m.quantity_delta,
            quantity_on_hand_after=m.quantity_on_hand_after,
            unit_cost_paise=m.unit_cost_paise if show else None,
            reverses_movement_id=m.reverses_movement_id,
            reason=reason,
            occurred_at=m.occurred_at,
            initiated_by_name=uname,
        )
        for m, txn_type, status, reason, pname, unit, uname in rows
    ]


def _transaction_result(
    db: Session, ctx: ShopContext, txn: BusinessTransaction
) -> InventoryTransactionResult:
    db.flush()
    rows = db.execute(
        _movement_query()
        .where(StockMovement.shop_id == ctx.shop_id, StockMovement.transaction_id == txn.id)
        .order_by(Product.name, StockMovement.id)
    ).all()
    return InventoryTransactionResult(
        transaction_id=txn.id,
        txn_type=txn.txn_type,
        business_date=txn.business_date,
        movements=_movement_reads(ctx, rows),
    )


def list_movements(
    db: Session,
    ctx: ShopContext,
    *,
    product_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> MovementListResponse:
    _require(ctx, Permission.INVENTORY_VIEW)
    base = _movement_query().where(StockMovement.shop_id == ctx.shop_id)
    count = (
        select(func.count()).select_from(StockMovement).where(StockMovement.shop_id == ctx.shop_id)
    )
    if product_id is not None:
        base = base.where(StockMovement.product_id == product_id)
        count = count.where(StockMovement.product_id == product_id)
    rows = db.execute(
        base.order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return MovementListResponse(
        items=_movement_reads(ctx, rows),
        total=db.scalar(count) or 0,
        limit=limit,
        offset=offset,
        costs_visible=can_view_value(ctx),
    )


def _stock_item(ctx: ShopContext, product: Product, level: InventoryLevel | None) -> StockItem:
    qty = level.quantity_on_hand if level else ZERO
    show = can_view_value(ctx)
    cost = None
    if level and level.avg_cost_paise is not None:
        cost = level.avg_cost_paise
    elif product.default_cost_price_paise is not None:
        cost = product.default_cost_price_paise
    if qty <= 0:
        value: int | None = 0
    else:
        value = round_half_up(qty * cost) if cost is not None else None
    return StockItem(
        product_id=product.id,
        name=product.name,
        name_hi=product.name_hi,
        category_id=product.category_id,
        base_unit_code=product.base_unit_code,
        reorder_level=product.reorder_level,
        quantity_on_hand=qty,
        is_low=product.reorder_level is not None and ZERO < qty <= product.reorder_level,
        is_out=qty <= 0,
        archived=product.archived_at is not None,
        costs_visible=show,
        avg_cost_paise=cost if show else None,
        stock_value_paise=value if show else None,
    )


def _qty_expr():
    return func.coalesce(InventoryLevel.quantity_on_hand, 0)


def _tracked_products(ctx: ShopContext) -> Select:
    return (
        select(Product, InventoryLevel)
        .outerjoin(
            InventoryLevel,
            and_(
                InventoryLevel.shop_id == Product.shop_id,
                InventoryLevel.product_id == Product.id,
            ),
        )
        .where(
            Product.shop_id == ctx.shop_id,
            Product.track_stock.is_(True),
            Product.archived_at.is_(None),
        )
    )


def list_stock(
    db: Session,
    ctx: ShopContext,
    *,
    q: str | None,
    category_id: uuid.UUID | None,
    status: StockStatus,
    limit: int,
    offset: int,
) -> StockListResponse:
    _require(ctx, Permission.INVENTORY_VIEW)
    query = _tracked_products(ctx)
    if q:
        term = q.strip()[:120]
        pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            or_(
                Product.name.ilike(pattern, escape="\\"),
                Product.name_hi.ilike(pattern, escape="\\"),
                Product.barcode == term,
            )
        )
    if category_id is not None:
        query = query.where(Product.category_id == category_id)
    qty = _qty_expr()
    if status == "low":
        query = query.where(
            Product.reorder_level.is_not(None), qty > 0, qty <= Product.reorder_level
        )
    elif status == "out":
        query = query.where(qty <= 0)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(Product.name, Product.id).limit(limit).offset(offset)).all()
    return StockListResponse(
        items=[_stock_item(ctx, p, lvl) for p, lvl in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_stock(db: Session, ctx: ShopContext, product_id: uuid.UUID) -> StockItem:
    """Stock for one product (tracked or not, archived or not) of the caller's shop."""
    _require(ctx, Permission.INVENTORY_VIEW)
    row = db.execute(
        select(Product, InventoryLevel)
        .outerjoin(
            InventoryLevel,
            and_(
                InventoryLevel.shop_id == Product.shop_id,
                InventoryLevel.product_id == Product.id,
            ),
        )
        .where(Product.shop_id == ctx.shop_id, Product.id == product_id)
    ).first()
    if row is None:
        raise NotFound("Product not found.")
    return _stock_item(ctx, row[0], row[1])


def summary(db: Session, ctx: ShopContext) -> InventorySummary:
    _require(ctx, Permission.INVENTORY_VIEW)
    show = can_view_value(ctx)
    qty = _qty_expr()
    cost = func.coalesce(InventoryLevel.avg_cost_paise, Product.default_cost_price_paise)
    stmt = (
        select(
            func.count(),
            func.count().filter(
                Product.reorder_level.is_not(None), qty > 0, qty <= Product.reorder_level
            ),
            func.count().filter(qty <= 0),
            func.count().filter(qty < 0),
            func.coalesce(
                func.sum(case((and_(qty > 0, cost.is_not(None)), func.round(qty * cost)), else_=0)),
                0,
            ),
            func.count().filter(qty > 0, cost.is_(None)),
        )
        .select_from(Product)
        .outerjoin(
            InventoryLevel,
            and_(
                InventoryLevel.shop_id == Product.shop_id,
                InventoryLevel.product_id == Product.id,
            ),
        )
        .where(
            Product.shop_id == ctx.shop_id,
            Product.track_stock.is_(True),
            Product.archived_at.is_(None),
        )
    )
    tracked, low, out, negative, value, no_cost = db.execute(stmt).one()
    return InventorySummary(
        tracked_products=tracked,
        low_stock=low,
        out_of_stock=out,
        negative_stock=negative,
        costs_visible=show,
        stock_value_paise=int(value) if show else None,
        products_without_cost=no_cost if show else None,
    )


# ----------------------------------------------------------------------------- writes
def record_opening_stock(
    db: Session, ctx: ShopContext, data: OpeningStockCreate
) -> InventoryTransactionResult:
    _require(ctx, Permission.INVENTORY_ADJUST)
    products = _lock_products(db, ctx, (ln.product_id for ln in data.lines), for_new_stock=True)
    levels = _lock_levels(db, ctx, products)
    now = _now()
    txn = ledger.post_transaction(
        db,
        _actor(ctx),
        "opening_balance",
        ledger.PostOptions(
            occurred_at=now,
            reason=data.note,
            extra_audit={"kind": "opening_stock", "lines": len(data.lines)},
        ),
    )
    for line in sorted(data.lines, key=lambda ln: ln.product_id):
        level, product = levels[line.product_id], products[line.product_id]
        if line.unit_cost_paise is not None:
            level.avg_cost_paise = receipt_average(
                level.quantity_on_hand,
                level.avg_cost_paise,
                product.default_cost_price_paise,
                line.quantity,
                line.unit_cost_paise,
            )
        _move(
            db,
            level,
            txn=txn,
            movement_type="opening",
            delta=line.quantity,
            unit_cost_paise=line.unit_cost_paise,
            occurred_at=now,
        )
    return _transaction_result(db, ctx, txn)


def receive_goods(
    db: Session, ctx: ShopContext, data: GoodsReceiptCreate
) -> InventoryTransactionResult:
    _require(ctx, Permission.INVENTORY_RECEIVE)
    if data.supplier_id is not None:
        supplier = db.scalar(
            select(Supplier.id).where(
                Supplier.shop_id == ctx.shop_id,
                Supplier.id == data.supplier_id,
                Supplier.archived_at.is_(None),
            )
        )
        if supplier is None:
            raise NotFound("Supplier not found.")
    today = ledger.shop_today(db, ctx.shop_id)
    if data.received_on is not None and data.received_on > today:
        raise InvalidInput("The receipt date cannot be in the future.", code="FUTURE_DATE")
    products = _lock_products(db, ctx, (ln.product_id for ln in data.lines), for_new_stock=True)
    levels = _lock_levels(db, ctx, products)
    now = _now()
    lines = sorted(data.lines, key=lambda ln: ln.product_id)
    totals = {ln.product_id: round_half_up(ln.quantity * ln.unit_cost_paise) for ln in lines}
    txn = ledger.post_transaction(
        db,
        _actor(ctx),
        "goods_receipt",
        ledger.PostOptions(
            occurred_at=now,
            business_date=data.received_on or today,
            extra_audit={"lines": len(lines), "total_cost_paise": sum(totals.values())},
        ),
    )
    receipt = GoodsReceipt(
        id=uuid.uuid4(),
        shop_id=ctx.shop_id,
        transaction_id=txn.id,
        supplier_id=data.supplier_id,
        invoice_number=data.invoice_number,
        total_cost_paise=sum(totals.values()),
        received_at=now,
    )
    db.add(receipt)
    db.flush()
    for line in lines:
        level, product = levels[line.product_id], products[line.product_id]
        item = GoodsReceiptItem(
            id=uuid.uuid4(),
            shop_id=ctx.shop_id,
            goods_receipt_id=receipt.id,
            product_id=line.product_id,
            quantity=line.quantity,
            unit_cost_paise=line.unit_cost_paise,
            line_total_paise=totals[line.product_id],
        )
        db.add(item)
        level.avg_cost_paise = receipt_average(
            level.quantity_on_hand,
            level.avg_cost_paise,
            product.default_cost_price_paise,
            line.quantity,
            line.unit_cost_paise,
        )
        _move(
            db,
            level,
            txn=txn,
            movement_type="purchase_receipt",
            delta=line.quantity,
            unit_cost_paise=line.unit_cost_paise,
            occurred_at=now,
            reference=("goods_receipt_item", item.id),
        )
    db.flush()
    return _transaction_result(db, ctx, txn)


def adjust_stock(
    db: Session, ctx: ShopContext, data: AdjustmentCreate
) -> InventoryTransactionResult:
    _require(ctx, Permission.INVENTORY_ADJUST)
    products = _lock_products(db, ctx, [data.product_id], for_new_stock=True)
    product = products[data.product_id]
    level = _lock_levels(db, ctx, [data.product_id])[data.product_id]
    if level.quantity_on_hand - data.quantity < 0:
        raise _insufficient(product, level.quantity_on_hand, data.quantity)
    now = _now()
    txn = ledger.post_transaction(
        db,
        _actor(ctx),
        "stock_adjustment",
        ledger.PostOptions(occurred_at=now, reason=data.reason, extra_audit={"kind": data.kind}),
    )
    _move(
        db,
        level,
        txn=txn,
        movement_type=f"adjustment_{data.kind}",
        delta=-data.quantity,
        unit_cost_paise=_snapshot_cost(level, product),
        occurred_at=now,
    )
    return _transaction_result(db, ctx, txn)


def post_count(db: Session, ctx: ShopContext, data: StockCountCreate) -> InventoryTransactionResult:
    """Record a physical count: system vs counted vs difference, then adjust (design S5)."""
    _require(ctx, Permission.INVENTORY_ADJUST)
    products = _lock_products(db, ctx, (ln.product_id for ln in data.lines), for_new_stock=True)
    levels = _lock_levels(db, ctx, products)
    stale = [
        {"product_id": str(ln.product_id), "current": str(levels[ln.product_id].quantity_on_hand)}
        for ln in data.lines
        if levels[ln.product_id].quantity_on_hand != ln.expected_system_quantity
    ]
    if stale:
        raise Conflict(
            "Stock changed while you were counting. Check the latest quantities and count again.",
            code="COUNT_STALE",
            details={"products": stale},
        )
    now = _now()
    txn = ledger.post_transaction(
        db,
        _actor(ctx),
        "stock_count",
        ledger.PostOptions(
            occurred_at=now, reason=data.note, extra_audit={"lines": len(data.lines)}
        ),
    )
    count = StockCount(
        id=uuid.uuid4(),
        shop_id=ctx.shop_id,
        status="posted",
        started_by_user_id=ctx.user_id,
        posted_transaction_id=txn.id,
        notes=data.note,
        posted_at=now,
    )
    db.add(count)
    db.flush()
    for line in sorted(data.lines, key=lambda ln: ln.product_id):
        level, product = levels[line.product_id], products[line.product_id]
        system = level.quantity_on_hand
        difference = line.counted_quantity - system
        item = StockCountItem(
            id=uuid.uuid4(),
            shop_id=ctx.shop_id,
            stock_count_id=count.id,
            product_id=line.product_id,
            system_quantity=system,
            counted_quantity=line.counted_quantity,
            difference=difference,
            reason=line.reason,
        )
        db.add(item)
        db.flush()
        if difference != 0:
            _move(
                db,
                level,
                txn=txn,
                movement_type="adjustment_count",
                delta=difference,
                unit_cost_paise=_snapshot_cost(level, product),
                occurred_at=now,
                reference=("stock_count_item", item.id),
            )
    return _transaction_result(db, ctx, txn)


# ----------------------------------------------------------------------------- reversals
def _reverse_stock_movements(
    db: Session, original: BusinessTransaction, reversal: BusinessTransaction
) -> None:
    """Ledger reversal handler: write the exact negation of the original's stock movements.

    Registered for the inventory transaction types. ``opening_balance`` is shared with opening
    udhaar balances (Phase 5); the credit module must extend this handler, not replace it.
    """
    movements = db.scalars(
        select(StockMovement)
        .where(
            StockMovement.shop_id == original.shop_id,
            StockMovement.transaction_id == original.id,
        )
        .order_by(StockMovement.product_id, StockMovement.id)
    ).all()
    if not movements:
        return
    shop = _ShopScope(original.shop_id)
    products = _lock_products(db, shop, (m.product_id for m in movements), for_new_stock=False)
    levels = _lock_levels(db, shop, products)
    now = reversal.occurred_at
    for m in movements:
        level, product = levels[m.product_id], products[m.product_id]
        delta = -m.quantity_delta
        if delta < 0:
            if level.quantity_on_hand + delta < 0:
                raise _insufficient(product, level.quantity_on_hand, -delta)
            if m.movement_type in INFLOW_WITH_COST and m.unit_cost_paise is not None:
                level.avg_cost_paise = backout_average(
                    level.quantity_on_hand, level.avg_cost_paise, -delta, m.unit_cost_paise
                )
        movement_type = (
            "purchase_reversal" if m.movement_type == "purchase_receipt" else (m.movement_type)
        )
        _move(
            db,
            level,
            txn=reversal,
            movement_type=movement_type,
            delta=delta,
            unit_cost_paise=m.unit_cost_paise,
            occurred_at=now,
            reference=(m.reference_type, m.reference_id) if m.reference_type else None,
            reverses=m.id,
        )


class _ShopScope:
    """Minimal stand-in for ShopContext inside ledger handlers (shop only; no permissions)."""

    def __init__(self, shop_id: uuid.UUID) -> None:
        self.shop_id = shop_id


for _txn_type in INVENTORY_TXN_TYPES:
    ledger.register_reversal_handler(_txn_type, _reverse_stock_movements)


def reverse(
    db: Session, ctx: ShopContext, transaction_id: uuid.UUID, data: ReversalCreate
) -> InventoryTransactionResult:
    _require(ctx, Permission.INVENTORY_ADJUST)
    txn_type = db.scalar(
        select(BusinessTransaction.txn_type).where(
            BusinessTransaction.shop_id == ctx.shop_id, BusinessTransaction.id == transaction_id
        )
    )
    if txn_type is None:
        raise NotFound("Transaction not found.")
    has_movements = db.scalar(
        select(func.count())
        .select_from(StockMovement)
        .where(StockMovement.shop_id == ctx.shop_id, StockMovement.transaction_id == transaction_id)
    )
    if txn_type not in INVENTORY_TXN_TYPES or (txn_type == "opening_balance" and not has_movements):
        raise InvalidInput(
            "Only stock transactions can be reversed here.", code="REVERSAL_NOT_SUPPORTED"
        )
    reversal = ledger.reverse_transaction(db, _actor(ctx), transaction_id, reason=data.reason)
    return _transaction_result(db, ctx, reversal)
