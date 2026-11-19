"""Inventory API schemas.

Quantities are decimal strings in the product's base unit (NUMERIC(14,3)); money is integer
paise. Read models are built per caller: without ``inventory.view_value`` every cost/value field
is ``None`` and ``costs_visible`` is false, so costs can never reach staff.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.modules.catalog.schemas import Paise, _clean_name, _reject_float, _Strict, _to_scale_3

MAX_LINES = 100  # one request never posts more than this many products

PositiveQuantity = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(gt=0, max_digits=14, decimal_places=3, allow_inf_nan=False),
    AfterValidator(_to_scale_3),
]
NonNegativeQuantity = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(ge=0, max_digits=14, decimal_places=3, allow_inf_nan=False),
    AfterValidator(_to_scale_3),
]
SignedQuantity = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(max_digits=14, decimal_places=3, allow_inf_nan=False),
    AfterValidator(_to_scale_3),
]
AdjustmentKind = Literal["damage", "expiry", "loss"]
StockStatus = Literal["all", "low", "out"]


def _text(value: Any, *, max_length: int, required: bool) -> Any:
    if isinstance(value, str) or value is None:
        return _clean_name(value, max_length=max_length, required=required)
    return value


def _unique_products(lines: list[Any]) -> None:
    ids = [line.product_id for line in lines]
    if len(ids) != len(set(ids)):
        raise ValueError("each product may appear only once")


# ----------------------------------------------------------------------------- writes
class OpeningLine(_Strict):
    product_id: uuid.UUID
    quantity: PositiveQuantity
    unit_cost_paise: Paise | None = None


class OpeningStockCreate(_Strict):
    """Stock already on the shelf (onboarding or later). Owner/admin only."""

    lines: list[OpeningLine] = Field(min_length=1, max_length=MAX_LINES)
    note: str | None = None

    _note = field_validator("note", mode="before")(
        lambda v: _text(v, max_length=500, required=False)
    )

    @model_validator(mode="after")
    def _distinct(self) -> "OpeningStockCreate":
        _unique_products(self.lines)
        return self


class ReceiptLine(_Strict):
    product_id: uuid.UUID
    quantity: PositiveQuantity
    unit_cost_paise: Paise


class GoodsReceiptCreate(_Strict):
    """Goods received (with or without a supplier). The actual cost updates the average."""

    lines: list[ReceiptLine] = Field(min_length=1, max_length=MAX_LINES)
    supplier_id: uuid.UUID | None = None
    invoice_number: str | None = None
    received_on: date | None = None

    _invoice = field_validator("invoice_number", mode="before")(
        lambda v: _text(v, max_length=64, required=False)
    )

    @model_validator(mode="after")
    def _distinct(self) -> "GoodsReceiptCreate":
        _unique_products(self.lines)
        return self


class AdjustmentCreate(_Strict):
    """Stock reduction for damage, expiry or loss (never below zero; D-12b)."""

    product_id: uuid.UUID
    kind: AdjustmentKind
    quantity: PositiveQuantity
    reason: str

    _reason = field_validator("reason", mode="before")(
        lambda v: _text(v, max_length=500, required=True)
    )


class CountLine(_Strict):
    product_id: uuid.UUID
    counted_quantity: NonNegativeQuantity
    # The quantity the counter was shown; posting is refused if stock moved since (D-12c).
    expected_system_quantity: SignedQuantity
    reason: str | None = None

    _reason = field_validator("reason", mode="before")(
        lambda v: _text(v, max_length=120, required=False)
    )


class StockCountCreate(_Strict):
    lines: list[CountLine] = Field(min_length=1, max_length=MAX_LINES)
    note: str

    _note = field_validator("note", mode="before")(
        lambda v: _text(v, max_length=500, required=True)
    )

    @model_validator(mode="after")
    def _distinct(self) -> "StockCountCreate":
        _unique_products(self.lines)
        return self


class ReversalCreate(_Strict):
    reason: str

    _reason = field_validator("reason", mode="before")(
        lambda v: _text(v, max_length=500, required=True)
    )


# ----------------------------------------------------------------------------- reads
class StockItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    name: str
    name_hi: str | None
    category_id: uuid.UUID | None
    base_unit_code: str
    reorder_level: Decimal | None
    quantity_on_hand: Decimal
    is_low: bool
    is_out: bool
    archived: bool
    costs_visible: bool
    avg_cost_paise: int | None
    stock_value_paise: int | None


class StockListResponse(BaseModel):
    items: list[StockItem]
    total: int
    limit: int
    offset: int


class InventorySummary(BaseModel):
    tracked_products: int
    low_stock: int
    out_of_stock: int
    negative_stock: int
    costs_visible: bool
    stock_value_paise: int | None
    products_without_cost: int | None


class MovementRead(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    txn_type: str
    txn_status: str
    product_id: uuid.UUID
    product_name: str
    base_unit_code: str
    movement_type: str
    quantity_delta: Decimal
    quantity_on_hand_after: Decimal
    unit_cost_paise: int | None
    reverses_movement_id: uuid.UUID | None
    reason: str | None
    occurred_at: datetime
    initiated_by_name: str | None


class MovementListResponse(BaseModel):
    items: list[MovementRead]
    total: int
    limit: int
    offset: int
    costs_visible: bool


class InventoryTransactionResult(BaseModel):
    transaction_id: uuid.UUID
    txn_type: str
    business_date: date
    movements: list[MovementRead]
