from fastapi import APIRouter

from app.api.v1 import health
from app.modules.catalog.api import router as catalog_router
from app.modules.identity.api import router as auth_router
from app.modules.shops.api import router as shops_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth_router)
api_router.include_router(shops_router)
api_router.include_router(catalog_router)
