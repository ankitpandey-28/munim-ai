"""Request/response models for the catalogue (categories, products, aliases, prices, units).

These schemas validate *shape and values only*. They are NOT the security boundary: role
permissions and tenant isolation are enforced by the API dependencies (verified active shop,
``require(...)``), the service layer and PostgreSQL row-level security.

Conventions (shared with other modules):
- Inputs extend ``_Strict``: unknown fields are rejected (so ``shop_id`` can never be sent) and
  strings are trimmed.
- Money is integer paise only: floats, booleans and numeric strings are rejected.
- Quantities are ``Decimal`` (NUMERIC(14,3) in the database); floats are rejected so binary
  floating-point never enters the system.
- Limits come from the database schema (column lengths, CHECK constraints) or are technical
  (JavaScript-safe integers), not invented business rules.
"""

import unicodedata
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    field_validator,
    model_validator,
)

from app.shared.text import normalize_display_name, normalize_text

Language = Literal["hi", "hinglish", "en", "pa"]
PriceType = Literal["selling", "cost"]

# Technical bounds (not business rules):
MAX_PAISE = 2**53 - 1  # largest integer JavaScript represents exactly (BIGINT holds more)
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1  # sort_order is an INTEGER column
PRICE_FIELDS = frozenset({"selling_price_paise", "default_cost_price_paise"})


# ----------------------------------------------------------------------------- field types
def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send quantities as a decimal string or integer, not a float")
    if isinstance(value, bool):
        raise ValueError("a quantity cannot be a boolean")
    return value


Paise = Annotated[int, Strict(), Field(ge=0, le=MAX_PAISE)]


def _to_scale_3(value: Decimal) -> Decimal:
    """Store and return quantities exactly as NUMERIC(14,3) holds them ("30" -> "30.000"), so a
    response never depends on how the client happened to format the number."""
    return value.quantize(Decimal("0.001"))


Quantity = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(ge=0, max_digits=14, decimal_places=3, allow_inf_nan=False),
    AfterValidator(_to_scale_3),
]
Version = Annotated[int, Strict(), Field(ge=1, le=INT32_MAX)]
SortOrder = Annotated[int, Strict(), Field(ge=INT32_MIN, le=INT32_MAX)]


def _clean_name(value: str | None, *, max_length: int, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValueError("this field cannot be null")
        return None
    if any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ValueError("control characters are not allowed")
    cleaned = normalize_display_name(value)
    if not cleaned:
        if required:
            raise ValueError("cannot be empty")
        return None  # optional names: blank means "no value"
    if len(cleaned) > max_length:
        raise ValueError(f"must be at most {max_length} characters")
    return cleaned


def _name_input(value: Any, *, max_length: int, required: bool) -> Any:
    """Clean string/None input; leave other types for Pydantic's type validation to reject."""
    if isinstance(value, str) or value is None:
        return _clean_name(value, max_length=max_length, required=required)
    return value


def _clean_barcode(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if any(ch.isspace() or unicodedata.category(ch)[0] == "C" for ch in value):
        raise ValueError("barcode must not contain spaces or control characters")
    if len(value) > 64:
        raise ValueError("barcode must be at most 64 characters")
    return value


def _clean_unit_code(value: str | None) -> str | None:
    if value is None:
        raise ValueError("this field cannot be null")
    code = value.strip().lower()
    if not code or len(code) > 16:
        raise ValueError("unit code must be 1-16 characters")
    return code  # existence is checked against the units table by the service


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_some_change(data: BaseModel, ignore: set[str]) -> None:
    if not (data.model_fields_set - ignore):
        raise ValueError("provide at least one field to change")


# ----------------------------------------------------------------------------- units
class UnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    dimension: Literal["mass", "volume", "count"]
    factor_to_dimension_base: Decimal
    allows_decimal: bool
    name_en: str
    name_hi: str
    spoken_forms: list[str]


class UnitListResponse(BaseModel):
    items: list[UnitRead]


# ----------------------------------------------------------------------------- categories
class CategoryCreate(_Strict):
    name: str
    name_hi: str | None = None
    sort_order: SortOrder = 0

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: Any) -> Any:
        return _name_input(value, max_length=80, required=True)

    @field_validator("name_hi", mode="before")
    @classmethod
    def _name_hi(cls, value: Any) -> Any:
        return _name_input(value, max_length=80, required=False)


class CategoryUpdate(_Strict):
    """Partial update. ``product_categories`` has no version column, so there is no optimistic
    concurrency for categories (last write wins; documented model limitation)."""

    name: str | None = None
    name_hi: str | None = None
    sort_order: SortOrder | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: Any) -> Any:
        return _name_input(value, max_length=80, required=True)

    @field_validator("name_hi", mode="before")
    @classmethod
    def _name_hi(cls, value: Any) -> Any:
        return _name_input(value, max_length=80, required=False)

    @field_validator("sort_order", mode="before")
    @classmethod
    def _sort_not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("this field cannot be null")
        return value

    @model_validator(mode="after")
    def _some_change(self) -> "CategoryUpdate":
        _require_some_change(self, set())
        return self


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    name_hi: str | None
    sort_order: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CategoryListResponse(BaseModel):
    """Categories are few per shop, so the list is returned whole (no paging parameters)."""

    items: list[CategoryRead]
    total: int


# ----------------------------------------------------------------------------- products
class _ProductFields(_Strict):
    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def _name(cls, value: Any) -> Any:
        return _name_input(value, max_length=120, required=True)

    @field_validator("name_hi", mode="before", check_fields=False)
    @classmethod
    def _name_hi(cls, value: Any) -> Any:
        return _name_input(value, max_length=120, required=False)

    @field_validator("barcode", mode="before", check_fields=False)
    @classmethod
    def _barcode(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _clean_barcode(value.strip())
        return value

    @field_validator("base_unit_code", mode="before", check_fields=False)
    @classmethod
    def _unit(cls, value: Any) -> Any:
        if isinstance(value, str) or value is None:
            return _clean_unit_code(value)
        return value


class ProductCreate(_ProductFields):
    """New product. Initial prices are recorded in price history by the service."""

    name: str
    name_hi: str | None = None
    category_id: uuid.UUID | None = None
    base_unit_code: str
    is_loose: Annotated[bool, Strict()] = False
    selling_price_paise: Paise
    default_cost_price_paise: Paise | None = None
    reorder_level: Quantity | None = None
    barcode: str | None = None


class ProductUpdate(_ProductFields):
    """Partial update with optimistic concurrency (``version`` must equal the current row).

    Prices are NOT accepted here: they change only through ``POST /products/{id}/prices`` so
    every change is recorded in price history.
    """

    version: Version
    name: str | None = None
    name_hi: str | None = None
    category_id: uuid.UUID | None = None
    base_unit_code: str | None = None
    is_loose: Annotated[bool, Strict()] | None = None
    reorder_level: Quantity | None = None
    barcode: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_prices(cls, data: Any) -> Any:
        if isinstance(data, dict) and PRICE_FIELDS & data.keys():
            raise ValueError(
                "prices cannot be changed here; use POST /catalog/products/{id}/prices"
            )
        return data

    @field_validator("is_loose", mode="before")
    @classmethod
    def _is_loose_not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("this field cannot be null")
        return value

    @model_validator(mode="after")
    def _some_change(self) -> "ProductUpdate":
        _require_some_change(self, {"version"})
        return self


class ProductRead(BaseModel):
    """Product as returned by the API. Build it with ``from_model(product, include_costs=...)``
    so callers without cost visibility never receive the cost price."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    name_hi: str | None
    category_id: uuid.UUID | None
    base_unit_code: str
    is_loose: bool
    selling_price_paise: int
    default_cost_price_paise: int | None
    costs_visible: bool
    reorder_level: Decimal | None
    barcode: str | None
    archived_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, product: Any, *, include_costs: bool) -> "ProductRead":
        return cls(
            id=product.id,
            name=product.name,
            name_hi=product.name_hi,
            category_id=product.category_id,
            base_unit_code=product.base_unit_code,
            is_loose=product.is_loose,
            selling_price_paise=product.selling_price_paise,
            default_cost_price_paise=product.default_cost_price_paise if include_costs else None,
            costs_visible=include_costs,
            reorder_level=product.reorder_level,
            barcode=product.barcode,
            archived_at=product.archived_at,
            version=product.version,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )


class ProductListResponse(BaseModel):
    items: list[ProductRead]
    total: int
    limit: int
    offset: int


class ProductListParams(_Strict):
    """Query parameters for listing/searching products."""

    q: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    include_archived: bool = False
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=100_000)

    @field_validator("q")
    @classmethod
    def _blank_query(cls, value: str | None) -> str | None:
        return value or None


# ----------------------------------------------------------------------------- aliases
class ProductAliasCreate(_Strict):
    alias_text: str
    language: Language | None = None

    @field_validator("alias_text", mode="before")
    @classmethod
    def _alias(cls, value: Any) -> Any:
        if not isinstance(value, str) and value is not None:
            return value
        cleaned = _clean_name(value, max_length=120, required=True)
        normalized = normalize_text(cleaned or "")
        if not normalized:
            raise ValueError("alias must contain letters or digits")
        if len(normalized) > 120:
            raise ValueError("alias is too long once normalised")
        return cleaned


class ProductAliasRead(BaseModel):
    """Internal matching keys (normalized_text, phonetic_key) are deliberately not exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    alias_text: str
    language: str | None
    source: Literal["seed", "manual", "learned"]
    created_at: datetime


class ProductAliasListResponse(BaseModel):
    items: list[ProductAliasRead]


# ----------------------------------------------------------------------------- prices
class ProductPriceUpdate(_Strict):
    """Change selling and/or cost price with optimistic concurrency on the product.

    Omitted prices are unchanged; null is rejected (a price-history row always needs a value).
    The service appends history only for prices whose value actually changes.
    """

    version: Version
    selling_price_paise: Paise | None = None
    default_cost_price_paise: Paise | None = None

    @field_validator("selling_price_paise", "default_cost_price_paise", mode="before")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("omit a price to leave it unchanged; null is not allowed")
        return value

    @model_validator(mode="after")
    def _some_price(self) -> "ProductPriceUpdate":
        if not (self.model_fields_set & PRICE_FIELDS):
            raise ValueError("provide selling_price_paise and/or default_cost_price_paise")
        return self


class ProductPriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    price_type: PriceType
    price_paise: int
    effective_from: datetime
    set_by_user_id: uuid.UUID
    source: Literal["manual", "voice", "system"]
    created_at: datetime


class ProductPriceListResponse(BaseModel):
    items: list[ProductPriceRead]
    total: int
    limit: int
    offset: int
    costs_visible: bool

    @classmethod
    def from_models(
        cls, rows: list[Any], *, total: int, limit: int, offset: int, include_costs: bool
    ) -> "ProductPriceListResponse":
        """Defence in depth: cost rows are dropped here even if a query returned them. The
        service must ALSO filter cost rows in SQL so ``total`` is correct for the caller."""
        visible = [r for r in rows if include_costs or r.price_type != "cost"]
        return cls(
            items=[ProductPriceRead.model_validate(r) for r in visible],
            total=total,
            limit=limit,
            offset=offset,
            costs_visible=include_costs,
        )
