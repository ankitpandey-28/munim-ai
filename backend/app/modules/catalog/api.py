"""Catalogue endpoints: /api/v1/catalog/*

HTTP only: validation via schemas, permission dependencies, one commit per successful request.
Business rules, tenant scoping and role-specific output (cost hiding) live in
``app.modules.catalog.service``. The shop is always the session's verified active shop
(``require`` -> ``get_shop_context``); no endpoint accepts a shop id.

Idempotency (``Idempotency-Key`` header, same pattern as the shops API) is required on writes
that could duplicate or reapply effects on retry: creates, partial updates, alias creation and
price changes. Archive and alias deletion are naturally retry-safe (a repeat returns 409 /
404 without side effects) and, like member deactivation, are not wrapped.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.deps import DbSession, require
from app.api.idempotent import run_idempotent
from app.modules.catalog import service
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
)
from app.modules.shops.context import ShopContext
from app.modules.shops.permissions import Permission

router = APIRouter(prefix="/catalog", tags=["catalog"])

CanView = Annotated[ShopContext, Depends(require(Permission.CATALOG_VIEW))]
CanManage = Annotated[ShopContext, Depends(require(Permission.CATALOG_MANAGE))]
CanManagePrices = Annotated[ShopContext, Depends(require(Permission.CATALOG_MANAGE_PRICES))]

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


# ----------------------------------------------------------------------------- units
@router.get("/units", response_model=UnitListResponse, summary="Units of measure (read-only)")
def list_units(db: DbSession, ctx: CanView) -> UnitListResponse:
    return service.list_units(db, ctx)


# ----------------------------------------------------------------------------- categories
@router.post(
    "/categories",
    status_code=status.HTTP_201_CREATED,
    response_model=CategoryRead,
    summary="Create a category. Idempotent.",
)
def create_category(body: CategoryCreate, request: Request, db: DbSession, ctx: CanManage):
    return run_idempotent(
        db, request, user_id=ctx.user_id, shop_id=ctx.shop_id, payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: (service.create_category(db, ctx, body), None),
    )  # fmt: skip


@router.get("/categories", response_model=CategoryListResponse, summary="List categories")
def list_categories(
    db: DbSession, ctx: CanView, include_archived: bool = False
) -> CategoryListResponse:
    return service.list_categories(db, ctx, include_archived=include_archived)


@router.get("/categories/{category_id}", response_model=CategoryRead, summary="Get a category")
def get_category(category_id: uuid.UUID, db: DbSession, ctx: CanView) -> CategoryRead:
    return service.get_category(db, ctx, category_id)


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryRead,
    summary="Update a category (name, Hindi name, sort order). Idempotent.",
)
def update_category(
    category_id: uuid.UUID, body: CategoryUpdate, request: Request, db: DbSession, ctx: CanManage
):
    return run_idempotent(
        db, request, user_id=ctx.user_id, shop_id=ctx.shop_id, payload=body,
        status_code=status.HTTP_200_OK,
        operation=lambda: (service.update_category(db, ctx, category_id, body), None),
    )  # fmt: skip


@router.post(
    "/categories/{category_id}/archive",
    response_model=CategoryRead,
    summary="Archive a category (refused while active products use it; never deleted)",
)
def archive_category(category_id: uuid.UUID, db: DbSession, ctx: CanManage) -> CategoryRead:
    result = service.archive_category(db, ctx, category_id)
    db.commit()
    return result


# ----------------------------------------------------------------------------- products
@router.post(
    "/products",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductRead,
    summary="Create a product (initial prices recorded in history). Idempotent.",
)
def create_product(
    body: ProductCreate,
    request: Request,
    db: DbSession,
    ctx: CanManage,
    _prices: CanManagePrices,  # a new product always sets prices
):
    return run_idempotent(
        db, request, user_id=ctx.user_id, shop_id=ctx.shop_id, payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: (service.create_product(db, ctx, body), None),
    )  # fmt: skip


@router.get(
    "/products",
    response_model=ProductListResponse,
    summary="List/search products (name, Hindi name, alias, exact barcode) with paging",
)
def list_products(
    params: Annotated[ProductListParams, Query()], db: DbSession, ctx: CanView
) -> ProductListResponse:
    return service.list_products(db, ctx, params)


@router.get(
    "/products/{product_id}",
    response_model=ProductRead,
    summary="Get a product (archived products remain readable)",
)
def get_product(product_id: uuid.UUID, db: DbSession, ctx: CanView) -> ProductRead:
    return service.get_product(db, ctx, product_id)


@router.patch(
    "/products/{product_id}",
    response_model=ProductRead,
    summary="Update product details with version check (prices: use /prices). Idempotent.",
)
def update_product(
    product_id: uuid.UUID, body: ProductUpdate, request: Request, db: DbSession, ctx: CanManage
):
    return run_idempotent(
        db, request, user_id=ctx.user_id, shop_id=ctx.shop_id, payload=body,
        status_code=status.HTTP_200_OK,
        operation=lambda: (service.update_product(db, ctx, product_id, body), None),
    )  # fmt: skip


@router.post(
    "/products/{product_id}/archive",
    response_model=ProductRead,
    summary="Archive a product (barcode stays reserved; never deleted)",
)
def archive_product(product_id: uuid.UUID, db: DbSession, ctx: CanManage) -> ProductRead:
    result = service.archive_product(db, ctx, product_id)
    db.commit()
    return result


# ----------------------------------------------------------------------------- aliases
@router.get(
    "/products/{product_id}/aliases",
    response_model=ProductAliasListResponse,
    summary="List a product's aliases",
)
def list_aliases(product_id: uuid.UUID, db: DbSession, ctx: CanView) -> ProductAliasListResponse:
    return service.list_aliases(db, ctx, product_id)


@router.post(
    "/products/{product_id}/aliases",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductAliasRead,
    summary="Add an alias to a product. Idempotent.",
)
def add_alias(
    product_id: uuid.UUID,
    body: ProductAliasCreate,
    request: Request,
    db: DbSession,
    ctx: CanManage,
):
    return run_idempotent(
        db, request, user_id=ctx.user_id, shop_id=ctx.shop_id, payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: (service.add_alias(db, ctx, product_id, body), None),
    )  # fmt: skip


@router.delete(
    "/products/{product_id}/aliases/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an alias (aliases are matching hints, not records of value)",
)
def remove_alias(
    product_id: uuid.UUID, alias_id: uuid.UUID, db: DbSession, ctx: CanManage
) -> Response:
    service.remove_alias(db, ctx, product_id, alias_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------------- prices
@router.get(
    "/products/{product_id}/prices",
    response_model=ProductPriceListResponse,
    summary="Price history, newest first (cost rows only with catalog.view_costs)",
)
def list_price_history(
    product_id: uuid.UUID,
    db: DbSession,
    ctx: CanView,
    price_type: Literal["selling", "cost"] | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ProductPriceListResponse:
    return service.list_price_history(
        db, ctx, product_id, price_type=price_type, limit=limit, offset=offset
    )


@router.post(
    "/products/{product_id}/prices",
    response_model=ProductRead,
    summary="Change selling and/or cost price with version check (history appended). Idempotent.",
)
def update_prices(
    product_id: uuid.UUID,
    body: ProductPriceUpdate,
    request: Request,
    db: DbSession,
    ctx: CanManagePrices,
):
    return run_idempotent(
        db, request, user_id=ctx.user_id, shop_id=ctx.shop_id, payload=body,
        status_code=status.HTTP_200_OK,
        operation=lambda: (service.update_prices(db, ctx, product_id, body), None),
    )  # fmt: skip
