"""SQLAlchemy engine, sessions and the transaction-local tenant context for RLS.

The engine is created lazily so the API can start (and report health) without a database.

Tenant context (docs/architecture.md §9.1, layers 5-6): the authenticated user id and the
verified active shop id are stored on the Session (``session.info["tenant"]``). At the start of
EVERY transaction an ``after_begin`` hook runs ``set_config(..., is_local => true)``, so the
values exist only inside that transaction and can never leak to another request through the
connection pool. With no context set, RLS policies see NULL and return/accept nothing.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class TenantContext:
    user_id: uuid.UUID | None = None
    shop_id: uuid.UUID | None = None


_SET_CONTEXT = text(
    "SELECT set_config('app.current_user_id', :user_id, true), "
    "set_config('app.current_shop_id', :shop_id, true)"
)


def _apply_context(connection, ctx: TenantContext) -> None:
    connection.execute(
        _SET_CONTEXT,
        {
            "user_id": str(ctx.user_id) if ctx.user_id else "",
            "shop_id": str(ctx.shop_id) if ctx.shop_id else "",
        },
    )


@event.listens_for(Session, "after_begin")
def _set_tenant_context_on_begin(session: Session, _transaction, connection) -> None:
    _apply_context(connection, session.info.get("tenant", TenantContext()))


def set_tenant_context(
    session: Session, *, user_id: uuid.UUID | None, shop_id: uuid.UUID | None
) -> None:
    """Set the tenant context for this session; applied immediately if a transaction is open
    and automatically at the start of every later transaction."""
    ctx = TenantContext(user_id=user_id, shop_id=shop_id)
    session.info["tenant"] = ctx
    if session.in_transaction():
        _apply_context(session.connection(), ctx)


def get_tenant_context(session: Session) -> TenantContext:
    return session.info.get("tenant", TenantContext())


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if settings.database_url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        connect_args={
            "connect_timeout": settings.database_connect_timeout,
            "application_name": "munim-api",
        },
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Iterator[Session]:
    """FastAPI dependency: one Session per request. Commits are explicit in services; anything
    not committed is rolled back when the request ends (including on errors)."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
