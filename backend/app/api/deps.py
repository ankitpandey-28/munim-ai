"""FastAPI dependencies: database session, authentication, verified shop context, permissions.

The shop context is NEVER taken from the URL or request body (architecture ADR-07): it comes
from the server-side session's ``active_shop_id`` and is re-verified against an *active*
membership on every request, then set transaction-locally for RLS.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, PermissionDenied
from app.core.security import client_ip, keyed_hash
from app.database.session import get_db_session, set_tenant_context
from app.modules.identity import service as auth_service
from app.modules.shops.context import ShopContext
from app.modules.shops.models import Shop, ShopMember
from app.modules.shops.permissions import Permission, has_permission

DbSession = Annotated[Session, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class PasswordChangeRequired(AppError):
    status_code = 403
    code = "PASSWORD_CHANGE_REQUIRED"


class NoActiveShop(AppError):
    status_code = 403
    code = "NO_ACTIVE_SHOP"


@dataclass
class RequestMeta:
    ip: str | None
    ip_hash: str | None
    user_agent: str | None


def get_request_meta(request: Request, settings: SettingsDep) -> RequestMeta:
    ip = client_ip(request, settings)
    return RequestMeta(
        ip=ip,
        ip_hash=keyed_hash(ip, purpose="ip", settings=settings) if ip else None,
        user_agent=request.headers.get("user-agent"),
    )


Meta = Annotated[RequestMeta, Depends(get_request_meta)]


def get_session_token(request: Request, settings: SettingsDep) -> str | None:
    return request.cookies.get(settings.session_cookie_name)


def get_auth_allow_password_change(
    db: DbSession, settings: SettingsDep, token: Annotated[str | None, Depends(get_session_token)]
) -> auth_service.AuthContext:
    """Authenticated user, even if they must change their password (for /me, logout,
    change-password)."""
    ctx = auth_service.authenticate_token(db, settings, token)
    set_tenant_context(db, user_id=ctx.user.id, shop_id=None)
    return ctx


def get_auth(
    ctx: Annotated[auth_service.AuthContext, Depends(get_auth_allow_password_change)],
) -> auth_service.AuthContext:
    if ctx.user.must_change_password:
        raise PasswordChangeRequired("Please change your temporary password to continue.")
    return ctx


AuthAnyDep = Annotated[auth_service.AuthContext, Depends(get_auth_allow_password_change)]
AuthDep = Annotated[auth_service.AuthContext, Depends(get_auth)]


def get_shop_context(db: DbSession, auth: AuthDep) -> ShopContext:
    shop_id = auth.session.active_shop_id
    if shop_id is None:
        raise NoActiveShop("Create a shop or choose one to continue.")
    row = db.execute(
        select(ShopMember, Shop)
        .join(Shop, Shop.id == ShopMember.shop_id)
        .where(
            ShopMember.shop_id == shop_id,
            ShopMember.user_id == auth.user.id,
            ShopMember.status == "active",
        )
    ).first()
    if row is None or row[1].status != "active":
        raise NoActiveShop("You no longer have access to this shop. Choose another shop.")
    membership, shop = row
    set_tenant_context(db, user_id=auth.user.id, shop_id=shop.id)
    return ShopContext(user=auth.user, session=auth.session, membership=membership, shop=shop)


ShopDep = Annotated[ShopContext, Depends(get_shop_context)]


def require(permission: Permission) -> Callable[[ShopContext], ShopContext]:
    def checker(ctx: ShopDep) -> ShopContext:
        if not has_permission(ctx.role, permission):
            raise PermissionDenied("You do not have permission to do this in this shop.")
        return ctx

    return checker
