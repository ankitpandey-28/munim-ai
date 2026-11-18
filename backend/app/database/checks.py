"""Database connectivity and session-identity checks used by the health endpoint."""

import logging
import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.database.identity import fetch_identity, runtime_identity_problems
from app.database.session import DatabaseNotConfiguredError, get_engine
from app.schemas.health import DatabaseHealth, DatabaseStatus, RoleCheck

logger = logging.getLogger(__name__)


def check_database(settings: Settings | None = None) -> DatabaseHealth:
    settings = settings or get_settings()
    try:
        engine = get_engine()
    except DatabaseNotConfiguredError:
        return DatabaseHealth(status=DatabaseStatus.NOT_CONFIGURED)

    start = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            identity = fetch_identity(conn)
    except SQLAlchemyError as exc:
        # Log the exception class only: driver messages can include host/user details.
        logger.warning("database health check failed", extra={"error_type": type(exc).__name__})
        return DatabaseHealth(status=DatabaseStatus.UNAVAILABLE, detail="connection failed")

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    problems = runtime_identity_problems(identity, settings)
    if problems:
        # Fixed problem codes and role/database names only; never URLs or passwords.
        logger.error(
            "runtime database connection failed the identity check",
            extra={"problems": problems},
        )
        return DatabaseHealth(
            status=DatabaseStatus.OK,
            role_check=RoleCheck.UNSAFE,
            latency_ms=latency_ms,
            detail="unsafe connection: " + ", ".join(problems),
        )
    return DatabaseHealth(status=DatabaseStatus.OK, role_check=RoleCheck.OK, latency_ms=latency_ms)
