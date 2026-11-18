from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class OverallStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class DatabaseStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


class RoleCheck(StrEnum):
    """Result of the runtime identity check (SV-2): the session must be the expected
    application role on the expected database, without SUPERUSER, BYPASSRLS or INHERIT."""

    OK = "ok"
    UNSAFE = "unsafe"
    SKIPPED = "skipped"


class DatabaseHealth(BaseModel):
    status: DatabaseStatus
    role_check: RoleCheck = RoleCheck.SKIPPED
    latency_ms: float | None = None
    detail: str | None = None


class HealthChecks(BaseModel):
    database: DatabaseHealth


class HealthResponse(BaseModel):
    status: OverallStatus
    service: str
    version: str
    environment: str
    timestamp: datetime
    uptime_seconds: float
    checks: HealthChecks
