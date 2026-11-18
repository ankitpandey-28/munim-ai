"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import configure_mappers

from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import OriginCheckMiddleware, RequestContextMiddleware
from app.core.startup import run_startup_checks
from app.database.session import dispose_engine
from app.models.registry import import_all_models

logger = logging.getLogger("app")

API_DESCRIPTION = """
Munim AI backend (Phase 2 foundation).

* Authentication: phone + password, Argon2id, server-side sessions in an httpOnly cookie.
* Every shop-scoped endpoint uses the session's verified active shop; PostgreSQL row-level
  security enforces isolation in the database as well.
* State-changing endpoints marked *Idempotent* require an `Idempotency-Key` header.
* Errors use one envelope: `{"error": {"code", "message", "details", "request_id"}}`.
"""


def create_app(settings: Settings | None = None, *, startup_checks: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    import_all_models()
    configure_mappers()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application starting",
            extra={"environment": settings.app_env.value, "version": settings.app_version},
        )
        if startup_checks:
            run_startup_checks(settings)
        yield
        dispose_engine()
        logger.info("application stopped")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        # Interactive docs are disabled in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    # Middleware order: last added runs first. Request id wraps everything.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.frontend_origin_list)
    if settings.cors_enabled and settings.frontend_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.frontend_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Idempotent-Replayed"],
        )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
