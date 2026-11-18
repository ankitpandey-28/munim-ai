"""Application settings, loaded from environment variables (and an optional .env file).

Secrets are typed as ``SecretStr`` so they never appear in reprs, logs or error messages.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app import __version__


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Validation errors must never echo input values (they may contain DB passwords).
        hide_input_in_errors=True,
    )

    app_name: str = "Munim AI API"
    app_env: Environment = Environment.DEVELOPMENT
    app_version: str = __version__
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    # Runtime role (munim_app). Optional in development so the API can start without a DB.
    database_url: SecretStr | None = None
    # Owner/migration role (munim_owner). Read only by Alembic.
    migration_database_url: SecretStr | None = None
    database_connect_timeout: int = Field(default=3, ge=1, le=30)

    # Expected identities, verified against the live session (app/database/identity.py).
    # These are names, not secrets (docs/database-design.md §8.1).
    database_name: str = "munim_ai"
    database_app_role: str = "munim_app"
    database_owner_role: str = "munim_owner"

    # ---- authentication / sessions (docs/architecture.md §6)
    # Key for HMAC-hashing phone numbers and IPs in login_attempts / audit_logs. Required in
    # production (>= 32 chars). In development a random per-process key is used if unset.
    auth_secret_key: SecretStr | None = None
    session_cookie_name: str = "munim_session"
    session_cookie_secure: bool = True  # browsers accept Secure cookies on http://localhost
    session_absolute_ttl_hours: int = Field(default=720, ge=1, le=2160)  # 30 days
    session_idle_ttl_hours: int = Field(default=168, ge=1, le=720)  # 7 days
    login_max_failures: int = Field(default=5, ge=3, le=20)
    login_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    login_ip_max_attempts: int = Field(default=30, ge=5, le=1000)  # per 10 minutes
    registration_ip_max_per_hour: int = Field(default=10, ge=1, le=1000)

    # ---- browser access
    # Comma-separated origins allowed to make state-changing requests (CSRF origin check) and,
    # if CORS_ENABLED, cross-origin calls. The Next.js same-origin proxy needs only its own origin.
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_enabled: bool = False
    # Client IP is taken from X-Forwarded-For only when the direct peer is one of these.
    trusted_proxy_ips: str = "127.0.0.1,::1"

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def frontend_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxy_ips.split(",") if p.strip()]

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if not self.is_production:
            return self
        problems = []
        if self.database_url is None:
            problems.append("DATABASE_URL is required")
        if self.auth_secret_key is None or len(self.auth_secret_key.get_secret_value()) < 32:
            problems.append("AUTH_SECRET_KEY of at least 32 characters is required")
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true")
        if not self.frontend_origin_list or any(
            not o.startswith("https://") for o in self.frontend_origin_list
        ):
            problems.append("FRONTEND_ORIGINS must list https:// origins only")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def _validate_separate_connections(self) -> "Settings":
        """Runtime and migration connections must be different URLs and different roles.

        Error messages name the variables only, never their values.
        """
        if self.database_url is None or self.migration_database_url is None:
            return self
        runtime = self.database_url.get_secret_value()
        migration = self.migration_database_url.get_secret_value()
        if runtime == migration:
            raise ValueError("DATABASE_URL and MIGRATION_DATABASE_URL must not be identical")
        if self.database_app_role == self.database_owner_role:
            raise ValueError("DATABASE_APP_ROLE and DATABASE_OWNER_ROLE must be different roles")
        try:
            runtime_user = make_url(runtime).username
            migration_user = make_url(migration).username
        except ArgumentError:
            raise ValueError(
                "DATABASE_URL or MIGRATION_DATABASE_URL is not a valid database URL"
            ) from None
        if runtime_user is not None and runtime_user == migration_user:
            raise ValueError("DATABASE_URL and MIGRATION_DATABASE_URL must use different roles")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
