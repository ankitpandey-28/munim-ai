"""Catalogue business logic: units, categories, products, aliases, prices.

Conventions (same as the shops module):
- Every function receives the verified ``ShopContext``; the shop is never taken from client
  input. Queries filter by ``ctx.shop_id`` explicitly AND run under PostgreSQL RLS.
- A record from another shop is reported as ``NotFound`` (indistinguishable from missing).
- Permissions are checked here (defence in depth) as well as by the API dependencies.
- Functions never commit: the API layer commits once per request (with idempotency).
- Public functions return API schemas built for the caller's role, so cost prices can never
  reach a user without ``catalog.view_costs``.
- Pre-checks give clear 409s; a savepoint guard maps the database's unique indexes to the
  same 409s if two requests race past the pre-checks.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, InvalidInput, NotFound, PermissionDenied
from app.modules.audit import service as audit
from app.modules.catalog.models import (
    Product,
    ProductAlias,
    ProductCategory,
    ProductPrice,
    Unit,
)
from app.modules.catalog.schemas import (
    CategoryCreate,
    CategoryListResponse,
    CategoryRead,
    CategoryUpdate,
    ProductAliasCreate,
    ProductAliasListResponse,
    ProductAliasRead,
    ProductCreate,
    ProductListParams,
    ProductListResponse,
    ProductPriceListResponse,
    ProductPriceUpdate,
    ProductRead,
    ProductUpdate,
    UnitListResponse,
    UnitRead,
)
from app.modules.inventory.models import InventoryLevel, StockMovement
from app.modules.shops.context import ShopContext
from app.modules.shops.permissions import Permission, has_permission
from app.shared.text import normalize_text

PRODUCT_AUDIT_FIELDS = (
    "name", "name_hi", "category_id", "base_unit_code", "is_loose", "track_stock",
    "selling_price_paise",
    "default_cost_price_paise", "reorder_level", "barcode", "archived_at", "version",
)  # fmt: skip
CATEGORY_AUDIT_FIELDS = ("name", "name_hi", "sort_order", "archived_at")


# ----------------------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now(UTC)


def _require(ctx: ShopContext, permission: Permission) -> None:
    if not has_permission(ctx.role, permission):
        raise PermissionDenied("You do not have permission to do this in this shop.")


def can_view_costs(ctx: ShopContext) -> bool:
    return has_permission(ctx.role, Permission.CATALOG_VIEW_COSTS)


def _snapshot(obj: object, fields: tuple[str, ...]) -> dict:
    return {f: getattr(obj, f) for f in fields}


def _like_pattern(term: str) -> str:
    """Substring pattern with LIKE wildcards escaped (backslash is the escape character)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@contextmanager
def _unique_guard(db: Session, conflicts: dict[str, AppError]) -> Iterator[None]:
    """Run the enclosed changes inside a SAVEPOINT; a unique-index violation named in
    ``conflicts`` becomes that clean error instead of a 500 (concurrent duplicate requests)."""
    savepoint = db.begin_nested()
    try:
        yield
        db.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in conflicts:
            raise conflicts[constraint] from None
        raise
    else:
        savepoint.commit()


def _category_name_taken() -> Conflict:
    return Conflict("A category with this name already exists.", code="CATEGORY_NAME_TAKEN")


def _product_name_taken() -> Conflict:
    return Conflict("A product with this name already exists.", code="PRODUCT_NAME_TAKEN")


def _barcode_taken() -> Conflict:
    return Conflict("Another product already uses this barcode.", code="BARCODE_TAKEN")


def _alias_exists() -> Conflict:
    return Conflict("This product already has this alias.", code="ALIAS_EXISTS")


CATEGORY_CONFLICTS = {"uq_product_categories_shop_id_lower_name_active": _category_name_taken()}
PRODUCT_CONFLICTS = {
    "uq_products_shop_id_lower_name_active": _product_name_taken(),
    "uq_products_shop_id_barcode": _barcode_taken(),
}
ALIAS_CONFLICTS = {"uq_product_aliases_shop_id_product_id_normalized_text": _alias_exists()}


# ----------------------------------------------------------------------------- units
def list_units(db: Session, ctx: ShopContext) -> UnitListResponse:
    _require(ctx, Permission.CATALOG_VIEW)
    units = db.execute(
        select(Unit).order_by(Unit.dimension, Unit.factor_to_dimension_base, Unit.code)
    ).scalars()
    return UnitListResponse(items=[UnitRead.model_validate(u) for u in units])


def _get_unit(db: Session, code: str) -> Unit:
    unit = db.get(Unit, code)
    if unit is None:
        raise InvalidInput(f"Unknown unit '{code}'.", code="INVALID_UNIT")
    return unit


def _check_unit_rules(unit: Unit, *, is_loose: bool, reorder_level: Decimal | None) -> None:
    if is_loose and not unit.allows_decimal:
        raise InvalidInput(
            f"Loose (weighed/measured) products need a decimal unit; '{unit.code}' is counted "
            "in whole numbers.",
            code="LOOSE_REQUIRES_DECIMAL_UNIT",
        )
    if reorder_level is not None and not unit.allows_decimal and reorder_level % 1 != 0:
        raise InvalidInput(
            f"Reorder level must be a whole number for unit '{unit.code}'.",
            code="DECIMAL_NOT_ALLOWED_FOR_UNIT",
        )


# ----------------------------------------------------------------------------- categories
def _category_query(ctx: ShopContext, category_id: uuid.UUID) -> Select:
    return select(ProductCategory).where(
        ProductCategory.shop_id == ctx.shop_id, ProductCategory.id == category_id
    )


def _get_category(
    db: Session, ctx: ShopContext, category_id: uuid.UUID, *, lock: bool = False
) -> ProductCategory:
    query = _category_query(ctx, category_id)
    if lock:
        query = query.with_for_update()
    category = db.execute(query).scalar_one_or_none()
    if category is None:
        raise NotFound("Category not found.")
    return category


def _category_name_in_use(
    db: Session, ctx: ShopContext, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    query = select(ProductCategory.id).where(
        ProductCategory.shop_id == ctx.shop_id,
        func.lower(ProductCategory.name) == name.lower(),
        ProductCategory.archived_at.is_(None),
    )
    if exclude_id is not None:
        query = query.where(ProductCategory.id != exclude_id)
    return db.execute(query.limit(1)).first() is not None


def list_categories(
    db: Session, ctx: ShopContext, *, include_archived: bool = False
) -> CategoryListResponse:
    _require(ctx, Permission.CATALOG_VIEW)
    query = select(ProductCategory).where(ProductCategory.shop_id == ctx.shop_id)
    if not include_archived:
        query = query.where(ProductCategory.archived_at.is_(None))
    rows = (
        db.execute(query.order_by(ProductCategory.sort_order, func.lower(ProductCategory.name)))
        .scalars()
        .all()
    )
    return CategoryListResponse(
        items=[CategoryRead.model_validate(r) for r in rows], total=len(rows)
    )


def get_category(db: Session, ctx: ShopContext, category_id: uuid.UUID) -> CategoryRead:
    _require(ctx, Permission.CATALOG_VIEW)
    return CategoryRead.model_validate(_get_category(db, ctx, category_id))


def create_category(db: Session, ctx: ShopContext, data: CategoryCreate) -> CategoryRead:
    _require(ctx, Permission.CATALOG_MANAGE)
    if _category_name_in_use(db, ctx, data.name):
        raise _category_name_taken()
    category = ProductCategory(
        shop_id=ctx.shop_id, name=data.name, name_hi=data.name_hi, sort_order=data.sort_order
    )
    with _unique_guard(db, CATEGORY_CONFLICTS):
        db.add(category)
    audit.record(
        db,
        action="category.created",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product_category",
        entity_id=category.id,
        after=_snapshot(category, CATEGORY_AUDIT_FIELDS),
    )
    return CategoryRead.model_validate(category)


def update_category(
    db: Session, ctx: ShopContext, category_id: uuid.UUID, data: CategoryUpdate
) -> CategoryRead:
    """Partial update. No version column on categories: last write wins (documented)."""
    _require(ctx, Permission.CATALOG_MANAGE)
    category = _get_category(db, ctx, category_id, lock=True)
    if category.archived_at is not None:
        raise Conflict("Archived categories cannot be edited.", code="CATEGORY_ARCHIVED")
    changes = {
        k: v for k, v in data.model_dump(exclude_unset=True).items() if getattr(category, k) != v
    }
    if not changes:
        return CategoryRead.model_validate(category)
    if "name" in changes and _category_name_in_use(db, ctx, changes["name"], category.id):
        raise _category_name_taken()
    before = _snapshot(category, CATEGORY_AUDIT_FIELDS)
    with _unique_guard(db, CATEGORY_CONFLICTS):
        for field, value in changes.items():
            setattr(category, field, value)
    audit.record(
        db,
        action="category.updated",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product_category",
        entity_id=category.id,
        before=before,
        after=_snapshot(category, CATEGORY_AUDIT_FIELDS),
    )
    return CategoryRead.model_validate(category)


def archive_category(db: Session, ctx: ShopContext, category_id: uuid.UUID) -> CategoryRead:
    """Archive (never delete). Refused while active products use the category. The category
    row is locked FOR UPDATE; product creation locks it FOR SHARE, so they serialise."""
    _require(ctx, Permission.CATALOG_MANAGE)
    category = _get_category(db, ctx, category_id, lock=True)
    if category.archived_at is not None:
        raise Conflict("This category is already archived.", code="ALREADY_ARCHIVED")
    active_products = db.execute(
        select(func.count())
        .select_from(Product)
        .where(
            Product.shop_id == ctx.shop_id,
            Product.category_id == category.id,
            Product.archived_at.is_(None),
        )
    ).scalar_one()
    if active_products:
        raise Conflict(
            "This category still has active products. Move or archive them first.",
            code="CATEGORY_IN_USE",
            details={"active_products": active_products},
        )
    before = _snapshot(category, CATEGORY_AUDIT_FIELDS)
    category.archived_at = _now()
    db.flush()
    audit.record(
        db,
        action="category.archived",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product_category",
        entity_id=category.id,
        before=before,
        after=_snapshot(category, CATEGORY_AUDIT_FIELDS),
    )
    return CategoryRead.model_validate(category)


# ----------------------------------------------------------------------------- products
def _get_product(
    db: Session, ctx: ShopContext, product_id: uuid.UUID, *, lock: bool = False
) -> Product:
    query = select(Product).where(Product.shop_id == ctx.shop_id, Product.id == product_id)
    if lock:
        query = query.with_for_update()
    product = db.execute(query).scalar_one_or_none()
    if product is None:
        raise NotFound("Product not found.")
    return product


def _get_editable_product(db: Session, ctx: ShopContext, product_id: uuid.UUID) -> Product:
    product = _get_product(db, ctx, product_id, lock=True)
    if product.archived_at is not None:
        raise Conflict("Archived products cannot be edited.", code="PRODUCT_ARCHIVED")
    return product


def _check_version(product: Product, version: int) -> None:
    if product.version != version:
        raise Conflict(
            "This product was changed by someone else. Reload and try again.",
            code="VERSION_CONFLICT",
            details={"current_version": product.version},
        )


def _validate_category_for_product(
    db: Session, ctx: ShopContext, category_id: uuid.UUID | None
) -> None:
    """The category must belong to the active shop and be active. Locked FOR SHARE so it
    cannot be archived concurrently. Another shop's id is reported like a missing one."""
    if category_id is None:
        return
    category = db.execute(
        _category_query(ctx, category_id).with_for_update(read=True)
    ).scalar_one_or_none()
    if category is None:
        raise InvalidInput("Category not found in this shop.", code="INVALID_CATEGORY")
    if category.archived_at is not None:
        raise InvalidInput("This category is archived.", code="CATEGORY_ARCHIVED")


def _product_name_in_use(
    db: Session, ctx: ShopContext, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    query = select(Product.id).where(
        Product.shop_id == ctx.shop_id,
        func.lower(Product.name) == name.lower(),
        Product.archived_at.is_(None),
    )
    if exclude_id is not None:
        query = query.where(Product.id != exclude_id)
    return db.execute(query.limit(1)).first() is not None


def _check_barcode_free(
    db: Session, ctx: ShopContext, barcode: str | None, exclude_id: uuid.UUID | None = None
) -> None:
    """Barcodes stay reserved by archived products (approved rule L1)."""
    if barcode is None:
        return
    query = select(Product.archived_at).where(
        Product.shop_id == ctx.shop_id, Product.barcode == barcode
    )
    if exclude_id is not None:
        query = query.where(Product.id != exclude_id)
    holder = db.execute(query.limit(1)).first()
    if holder is None:
        return
    if holder.archived_at is not None:
        raise Conflict(
            "This barcode belongs to an archived product and stays reserved.",
            code="BARCODE_RESERVED_BY_ARCHIVED",
        )
    raise _barcode_taken()


def _record_price(
    db: Session, ctx: ShopContext, product: Product, price_type: str, paise: int, when: datetime
) -> ProductPrice:
    row = ProductPrice(
        shop_id=ctx.shop_id,
        product_id=product.id,
        price_type=price_type,
        price_paise=paise,
        effective_from=when,
        set_by_user_id=ctx.user_id,
        source="manual",
    )
    db.add(row)
    return row


def _product_read(ctx: ShopContext, product: Product) -> ProductRead:
    return ProductRead.from_model(product, include_costs=can_view_costs(ctx))


def create_product(db: Session, ctx: ShopContext, data: ProductCreate) -> ProductRead:
    """Create a product and record its initial prices in price history (approved rule)."""
    _require(ctx, Permission.CATALOG_MANAGE)
    _require(ctx, Permission.CATALOG_MANAGE_PRICES)  # a new product always sets prices
    unit = _get_unit(db, data.base_unit_code)
    _check_unit_rules(unit, is_loose=data.is_loose, reorder_level=data.reorder_level)
    _validate_category_for_product(db, ctx, data.category_id)
    if _product_name_in_use(db, ctx, data.name):
        raise _product_name_taken()
    _check_barcode_free(db, ctx, data.barcode)
    product = Product(shop_id=ctx.shop_id, **data.model_dump())
    now = _now()
    with _unique_guard(db, PRODUCT_CONFLICTS):
        db.add(product)
    _record_price(db, ctx, product, "selling", product.selling_price_paise, now)
    if product.default_cost_price_paise is not None:
        _record_price(db, ctx, product, "cost", product.default_cost_price_paise, now)
    db.flush()
    audit.record(
        db,
        action="product.created",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product",
        entity_id=product.id,
        after=_snapshot(product, PRODUCT_AUDIT_FIELDS),
    )
    return _product_read(ctx, product)


def get_product(db: Session, ctx: ShopContext, product_id: uuid.UUID) -> ProductRead:
    """Readable by id even when archived (approved rule 5)."""
    _require(ctx, Permission.CATALOG_VIEW)
    return _product_read(ctx, _get_product(db, ctx, product_id))


def list_products(db: Session, ctx: ShopContext, params: ProductListParams) -> ProductListResponse:
    """Search (name, Hindi name, aliases, exact barcode), category filter and pagination."""
    _require(ctx, Permission.CATALOG_VIEW)
    conditions = [Product.shop_id == ctx.shop_id]
    if not params.include_archived:
        conditions.append(Product.archived_at.is_(None))
    if params.category_id is not None:
        conditions.append(Product.category_id == params.category_id)
    if params.q:
        pattern = _like_pattern(params.q)
        normalized = normalize_text(params.q)
        matches = [
            Product.name.ilike(pattern, escape="\\"),
            Product.name_hi.ilike(pattern, escape="\\"),
            Product.barcode == params.q,
        ]
        if normalized:
            matches.append(
                exists().where(
                    ProductAlias.shop_id == Product.shop_id,
                    ProductAlias.product_id == Product.id,
                    ProductAlias.normalized_text.like(_like_pattern(normalized), escape="\\"),
                )
            )
        conditions.append(or_(*matches))
    total = db.execute(select(func.count()).select_from(Product).where(*conditions)).scalar_one()
    rows = (
        db.execute(
            select(Product)
            .where(*conditions)
            .order_by(func.lower(Product.name), Product.id)
            .limit(params.limit)
            .offset(params.offset)
        )
        .scalars()
        .all()
    )
    return ProductListResponse(
        items=[_product_read(ctx, p) for p in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


def _check_stock_guards(db: Session, ctx: ShopContext, product: Product, changes: dict) -> None:
    """Integrity rules once stock exists (D-12). The product row is already locked FOR UPDATE,
    and inventory writes lock it FOR SHARE, so these checks cannot race a stock movement."""
    if "base_unit_code" in changes:
        has_movements = db.scalar(
            select(
                exists().where(
                    StockMovement.shop_id == ctx.shop_id, StockMovement.product_id == product.id
                )
            )
        )
        if has_movements:
            raise Conflict(
                "The unit cannot change after stock has been recorded for this product.",
                code="UNIT_LOCKED",
            )
    if changes.get("track_stock") is False:
        on_hand = db.scalar(
            select(InventoryLevel.quantity_on_hand).where(
                InventoryLevel.shop_id == ctx.shop_id, InventoryLevel.product_id == product.id
            )
        )
        if on_hand is not None and on_hand != 0:
            raise Conflict(
                "Stock tracking can only be turned off when the stock is zero. "
                "Record a stock count first.",
                code="STOCK_NOT_ZERO",
            )


def update_product(
    db: Session, ctx: ShopContext, product_id: uuid.UUID, data: ProductUpdate
) -> ProductRead:
    """Partial update with optimistic concurrency. Prices are not accepted (schema-enforced);
    they change only through ``update_prices``."""
    _require(ctx, Permission.CATALOG_MANAGE)
    product = _get_editable_product(db, ctx, product_id)
    _check_version(product, data.version)
    changes = {
        k: v
        for k, v in data.model_dump(exclude_unset=True, exclude={"version"}).items()
        if getattr(product, k) != v
    }
    if not changes:
        return _product_read(ctx, product)
    unit_code = changes.get("base_unit_code", product.base_unit_code)
    unit = _get_unit(db, unit_code)
    _check_unit_rules(
        unit,
        is_loose=changes.get("is_loose", product.is_loose),
        reorder_level=changes.get("reorder_level", product.reorder_level),
    )
    if "category_id" in changes:
        _validate_category_for_product(db, ctx, changes["category_id"])
    if "name" in changes and _product_name_in_use(db, ctx, changes["name"], product.id):
        raise _product_name_taken()
    if "barcode" in changes:
        _check_barcode_free(db, ctx, changes["barcode"], product.id)
    _check_stock_guards(db, ctx, product, changes)
    before = _snapshot(product, PRODUCT_AUDIT_FIELDS)
    with _unique_guard(db, PRODUCT_CONFLICTS):
        for field, value in changes.items():
            setattr(product, field, value)
        product.version += 1
    audit.record(
        db,
        action="product.updated",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product",
        entity_id=product.id,
        before=before,
        after=_snapshot(product, PRODUCT_AUDIT_FIELDS),
    )
    return _product_read(ctx, product)


def archive_product(db: Session, ctx: ShopContext, product_id: uuid.UUID) -> ProductRead:
    """Archive (never delete). The barcode stays reserved; the name becomes reusable."""
    _require(ctx, Permission.CATALOG_MANAGE)
    product = _get_product(db, ctx, product_id, lock=True)
    if product.archived_at is not None:
        raise Conflict("This product is already archived.", code="ALREADY_ARCHIVED")
    before = _snapshot(product, PRODUCT_AUDIT_FIELDS)
    product.archived_at = _now()
    product.version += 1
    db.flush()
    audit.record(
        db,
        action="product.archived",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product",
        entity_id=product.id,
        before=before,
        after=_snapshot(product, PRODUCT_AUDIT_FIELDS),
    )
    return _product_read(ctx, product)


# ----------------------------------------------------------------------------- aliases
def list_aliases(db: Session, ctx: ShopContext, product_id: uuid.UUID) -> ProductAliasListResponse:
    _require(ctx, Permission.CATALOG_VIEW)
    product = _get_product(db, ctx, product_id)
    rows = db.execute(
        select(ProductAlias)
        .where(ProductAlias.shop_id == ctx.shop_id, ProductAlias.product_id == product.id)
        .order_by(ProductAlias.created_at, ProductAlias.id)
    ).scalars()
    return ProductAliasListResponse(items=[ProductAliasRead.model_validate(r) for r in rows])


def add_alias(
    db: Session, ctx: ShopContext, product_id: uuid.UUID, data: ProductAliasCreate
) -> ProductAliasRead:
    """Add a manual alias. ``normalized_text`` comes from app.shared.text; no transliteration
    or phonetic key is computed (phonetic_key stays NULL until the voice phase)."""
    _require(ctx, Permission.CATALOG_MANAGE)
    product = _get_editable_product(db, ctx, product_id)
    normalized = normalize_text(data.alias_text)
    if not normalized:  # the schema already rejects this; keep the invariant here too
        raise InvalidInput("Alias must contain letters or digits.", code="INVALID_ALIAS")
    duplicate = db.execute(
        select(ProductAlias.id).where(
            ProductAlias.shop_id == ctx.shop_id,
            ProductAlias.product_id == product.id,
            ProductAlias.normalized_text == normalized,
        )
    ).first()
    if duplicate is not None:
        raise _alias_exists()
    alias = ProductAlias(
        shop_id=ctx.shop_id,
        product_id=product.id,
        alias_text=data.alias_text,
        normalized_text=normalized,
        phonetic_key=None,
        language=data.language,
        source="manual",
    )
    with _unique_guard(db, ALIAS_CONFLICTS):
        db.add(alias)
    audit.record(
        db, action="product.alias_added", actor_user_id=ctx.user_id, shop_id=ctx.shop_id,
        entity_type="product_alias", entity_id=alias.id,
        after={"product_id": product.id, "alias_text": alias.alias_text,
               "language": alias.language},
    )  # fmt: skip
    return ProductAliasRead.model_validate(alias)


def remove_alias(db: Session, ctx: ShopContext, product_id: uuid.UUID, alias_id: uuid.UUID) -> None:
    """Delete an alias row (aliases are matching hints, not financial records; the runtime
    role is granted DELETE on product_aliases only). The removal is audited."""
    _require(ctx, Permission.CATALOG_MANAGE)
    product = _get_editable_product(db, ctx, product_id)
    alias = db.execute(
        select(ProductAlias).where(
            ProductAlias.shop_id == ctx.shop_id,
            ProductAlias.product_id == product.id,
            ProductAlias.id == alias_id,
        )
    ).scalar_one_or_none()
    if alias is None:
        raise NotFound("Alias not found.")
    snapshot = {"product_id": product.id, "alias_text": alias.alias_text, "source": alias.source}
    db.delete(alias)
    db.flush()
    audit.record(
        db,
        action="product.alias_removed",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product_alias",
        entity_id=alias_id,
        before=snapshot,
    )


# ----------------------------------------------------------------------------- prices
def list_price_history(
    db: Session,
    ctx: ShopContext,
    product_id: uuid.UUID,
    *,
    price_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ProductPriceListResponse:
    """Newest first. Without ``catalog.view_costs`` cost rows are excluded in SQL (so totals
    are right) and explicitly asking for cost history is refused."""
    _require(ctx, Permission.CATALOG_VIEW)
    include_costs = can_view_costs(ctx)
    if price_type == "cost" and not include_costs:
        raise PermissionDenied("You do not have permission to view cost prices.")
    product = _get_product(db, ctx, product_id)
    conditions = [ProductPrice.shop_id == ctx.shop_id, ProductPrice.product_id == product.id]
    if price_type is not None:
        conditions.append(ProductPrice.price_type == price_type)
    if not include_costs:
        conditions.append(ProductPrice.price_type != "cost")
    total = db.execute(
        select(func.count()).select_from(ProductPrice).where(*conditions)
    ).scalar_one()
    rows = (
        db.execute(
            select(ProductPrice)
            .where(*conditions)
            .order_by(ProductPrice.effective_from.desc(), ProductPrice.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return ProductPriceListResponse.from_models(
        list(rows), total=total, limit=limit, offset=offset, include_costs=include_costs
    )


def update_prices(
    db: Session, ctx: ShopContext, product_id: uuid.UUID, data: ProductPriceUpdate
) -> ProductRead:
    """Change selling and/or cost price. Updates the product and appends history rows in the
    caller's transaction, only for prices whose value actually changes. If nothing changes,
    the product (and its version) is left untouched."""
    _require(ctx, Permission.CATALOG_MANAGE_PRICES)
    product = _get_editable_product(db, ctx, product_id)
    _check_version(product, data.version)
    requested = data.model_dump(exclude_unset=True, exclude={"version"})
    changed = {
        field: value for field, value in requested.items() if getattr(product, field) != value
    }
    if not changed:
        return _product_read(ctx, product)
    before = {f: getattr(product, f) for f in changed}
    now = _now()
    for field, value in changed.items():
        setattr(product, field, value)
        price_type = "selling" if field == "selling_price_paise" else "cost"
        _record_price(db, ctx, product, price_type, value, now)
    product.version += 1
    db.flush()
    audit.record(
        db,
        action="product.price_changed",
        actor_user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        entity_type="product",
        entity_id=product.id,
        before=before | {"version": product.version - 1},
        after=changed | {"version": product.version},
    )
    return _product_read(ctx, product)
