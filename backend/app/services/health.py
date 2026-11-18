import time
from datetime import UTC, datetime

from app.core.config import Settings
from app.database.checks import check_database
from app.schemas.health import (
    DatabaseStatus,
    HealthChecks,
    HealthResponse,
    OverallStatus,
    RoleCheck,
)

_STARTED_AT = time.monotonic()


def get_health(settings: Settings) -> HealthResponse:
    database = check_database(settings)
    healthy_db = (
        database.status is DatabaseStatus.OK and database.role_check is not RoleCheck.UNSAFE
    )
    # A missing database is acceptable only outside production (local frontend work, CI unit tests).
    db_optional = database.status is DatabaseStatus.NOT_CONFIGURED and not settings.is_production
    overall = OverallStatus.OK if (healthy_db or db_optional) else OverallStatus.DEGRADED

    return HealthResponse(
        status=overall,
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env.value,
        timestamp=datetime.now(UTC),
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
        checks=HealthChecks(database=database),
    )
