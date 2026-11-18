"""Shop management endpoints. The shop is always the session's verified active shop."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthDep, DbSession, ShopDep, require
from app.api.idempotent import run_idempotent
from app.modules.shops import service
from app.modules.shops.context import ShopContext
from app.modules.shops.permissions import Permission
from app.modules.shops.schemas import (
    AuditEntryOut,
    AuditPage,
    CurrentShopOut,
    MemberAdd,
    MemberAdded,
    MemberOut,
    MemberPage,
    MemberUpdate,
    MyShopList,
    MyShopOut,
    ShopCreate,
    ShopOut,
    ShopUpdate,
    SwitchShopRequest,
)

router = APIRouter(tags=["shops"])

CanUpdateShop = Annotated[ShopContext, Depends(require(Permission.SHOP_UPDATE))]
CanViewMembers = Annotated[ShopContext, Depends(require(Permission.MEMBERS_VIEW))]
CanManageStaff = Annotated[ShopContext, Depends(require(Permission.MEMBERS_MANAGE_STAFF))]
CanViewAudit = Annotated[ShopContext, Depends(require(Permission.AUDIT_VIEW))]


def _current(shop, role: str) -> CurrentShopOut:
    return CurrentShopOut(shop=ShopOut.model_validate(shop), role=role)


@router.post(
    "/shops",
    status_code=status.HTTP_201_CREATED,
    response_model=CurrentShopOut,
    summary="Create a shop (caller becomes owner; it becomes the active shop). Idempotent.",
)
def create_shop(body: ShopCreate, request: Request, db: DbSession, auth: AuthDep):
    def operation():
        shop, member = service.create_shop(db, auth, body)
        return _current(shop, member.role), None

    return run_idempotent(
        db,
        request,
        user_id=auth.user.id,
        shop_id=None,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=operation,
    )


@router.get("/shops/mine", response_model=MyShopList, summary="Shops I am an active member of")
def my_shops(db: DbSession, auth: AuthDep) -> MyShopList:
    return MyShopList(
        items=[
            MyShopOut(
                shop_id=shop.id,
                name=shop.name,
                role=member.role,
                is_active=shop.id == auth.session.active_shop_id,
            )
            for shop, member in service.list_my_shops(db, auth)
        ]
    )


@router.post(
    "/session/active-shop",
    response_model=CurrentShopOut,
    summary="Switch the session's active shop (requires an active membership)",
)
def switch_shop(body: SwitchShopRequest, db: DbSession, auth: AuthDep) -> CurrentShopOut:
    shop, member = service.switch_shop(db, auth, body.shop_id)
    result = _current(shop, member.role)
    db.commit()
    return result


@router.get("/shops/current", response_model=CurrentShopOut, summary="The active shop")
def current_shop(ctx: ShopDep) -> CurrentShopOut:
    return _current(ctx.shop, ctx.role)


@router.patch(
    "/shops/current",
    response_model=ShopOut,
    summary="Update shop details (owner/admin; optimistic concurrency via version). Idempotent.",
)
def update_shop(body: ShopUpdate, request: Request, db: DbSession, ctx: CanUpdateShop):
    def operation():
        return ShopOut.model_validate(service.update_shop(db, ctx, body)), None

    return run_idempotent(
        db,
        request,
        user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        payload=body,
        status_code=status.HTTP_200_OK,
        operation=operation,
    )


@router.get("/shops/current/members", response_model=MemberPage, summary="List members")
def list_members(
    db: DbSession,
    ctx: CanViewMembers,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    include_removed: bool = False,
) -> MemberPage:
    items, total = service.list_members(
        db, ctx, limit=limit, offset=offset, include_removed=include_removed
    )
    return MemberPage(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/shops/current/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberAdded,
    summary="Add a member (owner: any role; admin: staff only). Idempotent.",
)
def add_member(body: MemberAdd, request: Request, db: DbSession, ctx: CanManageStaff):
    def operation():
        member, user, created = service.add_member(db, ctx, body)
        return MemberAdded(member=service.member_out(member, user), account_created=created), None

    return run_idempotent(
        db,
        request,
        user_id=ctx.user_id,
        shop_id=ctx.shop_id,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=operation,
    )


@router.patch(
    "/shops/current/members/{member_id}",
    response_model=MemberOut,
    summary="Change a member's role (owner only) or credit limit",
)
def update_member(
    member_id: uuid.UUID, body: MemberUpdate, db: DbSession, ctx: CanManageStaff
) -> MemberOut:
    member, user = service.update_member(db, ctx, member_id, body)
    result = service.member_out(member, user)
    db.commit()
    return result


@router.post(
    "/shops/current/members/{member_id}/deactivate",
    response_model=MemberOut,
    summary="Deactivate a membership (the last owner cannot be removed)",
)
def deactivate_member(member_id: uuid.UUID, db: DbSession, ctx: ShopDep) -> MemberOut:
    member, user = service.deactivate_member(db, ctx, member_id)
    result = service.member_out(member, user)
    db.commit()
    return result


@router.get(
    "/shops/current/audit-logs", response_model=AuditPage, summary="Audit trail (owner only)"
)
def audit_logs(
    db: DbSession,
    ctx: CanViewAudit,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> AuditPage:
    rows = service.list_audit(db, ctx, limit=limit, offset=offset)
    return AuditPage(
        items=[AuditEntryOut.model_validate(r, from_attributes=True) for r in rows],
        limit=limit,
        offset=offset,
    )
