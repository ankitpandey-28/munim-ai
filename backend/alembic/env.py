"""Alembic environment.

Migrations always run as the owner/migration role (MIGRATION_DATABASE_URL), never as the
runtime application role (docs/database-design.md §8.1).

Online mode verifies the live session identity (app/database/identity.py) before running any
migration and fails closed. Offline mode (``--sql``) only renders SQL and opens no connection,
so there is no session to verify; review generated SQL before applying it.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.database.identity import verify_migration_identity
from app.models.registry import import_all_models

Base = import_all_models()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _migration_url() -> str:
    settings = get_settings()
    if settings.migration_database_url is None:
        raise RuntimeError("MIGRATION_DATABASE_URL is not set; refusing to run migrations.")
    return settings.migration_database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(
        url=_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _migration_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # Fail closed BEFORE any migration runs: the live session must be the schema owner
        # (munim_owner) on munim_ai, not a superuser and not the runtime role.
        verify_migration_identity(connection, get_settings())
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
