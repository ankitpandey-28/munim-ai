from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse
from app.services.health import get_health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Application health")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Liveness plus dependency status. Always 200 so callers can read the body;
    ``status`` is ``degraded`` when a required dependency is unhealthy."""
    # The database check uses a blocking driver; keep it off the event loop.
    return await run_in_threadpool(get_health, settings)
