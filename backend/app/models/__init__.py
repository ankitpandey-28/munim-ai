"""SQLAlchemy declarative base and model registry.

No business tables exist yet (Phase 2.2 creates the schema). Domain models will import
``Base`` from here so Alembic sees a single metadata object.
"""

from app.models.base import Base

__all__ = ["Base"]
