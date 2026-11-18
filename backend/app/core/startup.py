"""Start-up safety checks (fail closed).

- Runtime database identity (app/database/identity.py): if the database is reachable and the
  session is NOT munim_app/munim_ai with safe attributes, the API refuses to start in every
  environment.
- If the database is unreachable: production refuses to start; development/test log a warning
  (so frontend work is possible without PostgreSQL) and the health check reports it.
- Production configuration itself is validated by Settings (app/core/config.py).
"""

import logging

from app.core.config import Settings
from app.database.checks import check_database
from app.schemas.health import DatabaseStatus, RoleCheck

logger = logging.getLogger("app.startup")


class UnsafeStartupError(RuntimeError):
    pass


def run_startup_checks(settings: Settings) -> None:
    result = check_database(settings)
    if result.status is DatabaseStatus.NOT_CONFIGURED:
        logger.warning("DATABASE_URL is not set; database features are unavailable")
        return
    if result.status is DatabaseStatus.UNAVAILABLE:
        if settings.is_production:
            raise UnsafeStartupError("database is unreachable; refusing to start in production")
        logger.warning("database is unreachable at start-up; continuing (non-production)")
        return
    if result.role_check is not RoleCheck.OK:
        # Codes only (e.g. "unexpected_role(expected munim_app), bypassrls"); never URLs.
        raise UnsafeStartupError(
            f"runtime database connection failed the identity check: {result.detail}"
        )
    logger.info("runtime database identity verified", extra={"latency_ms": result.latency_ms})
