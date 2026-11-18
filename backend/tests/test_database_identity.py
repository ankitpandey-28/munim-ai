"""Session-identity safety: runtime (munim_app) and migration (munim_owner) connections.

No real database is used: the identity rules are pure functions, and the health check is
exercised with a fake engine. Every test that touches configuration uses a sentinel password
and asserts it never appears in responses, exceptions or logs.
"""

import ast
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.database import checks
from app.database.identity import (
    SessionIdentity,
    UnsafeDatabaseIdentityError,
    migration_identity_problems,
    runtime_identity_problems,
    verify_migration_identity,
)
from app.schemas.health import DatabaseStatus, RoleCheck

SENTINEL = "Zz9-SENTINEL-pw_7Qx"
RUNTIME_URL = f"postgresql+psycopg://munim_app:{SENTINEL}@localhost:5432/munim_ai"
MIGRATION_URL = f"postgresql+psycopg://munim_owner:{SENTINEL}x@localhost:5432/munim_ai"

APP_OK = SessionIdentity(
    login_role="munim_app",
    effective_role="munim_app",
    database="munim_ai",
    is_superuser=False,
    bypass_rls=False,
    inherit=False,
    owns_database=False,
)
OWNER_OK = SessionIdentity(
    login_role="munim_owner",
    effective_role="munim_owner",
    database="munim_ai",
    is_superuser=False,
    bypass_rls=False,
    inherit=True,
    owns_database=True,
)


@pytest.fixture
def db_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=RUNTIME_URL,
        migration_database_url=MIGRATION_URL,
    )


# --------------------------------------------------------------------------- fakes
class _Result:
    def __init__(self, row: dict | None) -> None:
        self._row = row

    def mappings(self) -> "_Result":
        return self

    def one_or_none(self) -> dict | None:
        return self._row


class _Connection:
    def __init__(self, identity: SessionIdentity | None) -> None:
        self._row = None if identity is None else vars(identity).copy()
        self.rolled_back = False

    def execute(self, _statement):
        return _Result(self._row)

    def rollback(self) -> None:
        self.rolled_back = True

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exc) -> None:
        return None


class _Engine:
    def __init__(self, identity: SessionIdentity | None = None, error: Exception | None = None):
        self._identity = identity
        self._error = error

    def connect(self) -> _Connection:
        if self._error is not None:
            raise self._error
        return _Connection(self._identity)


# --------------------------------------------------------------------------- runtime rules
def test_runtime_correct_role_and_database(db_settings: Settings) -> None:
    assert runtime_identity_problems(APP_OK, db_settings) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"is_superuser": True}, "superuser"),
        ({"bypass_rls": True}, "bypassrls"),
        ({"inherit": True}, "inherit"),
        ({"owns_database": True}, "owns_database"),
    ],
)
def test_runtime_rejects_unsafe_attributes(db_settings: Settings, change: dict, problem: str):
    assert problem in runtime_identity_problems(replace(APP_OK, **change), db_settings)


@pytest.mark.parametrize(
    "change",
    [
        {"login_role": "munim_owner", "effective_role": "munim_owner"},  # wrong role in URL
        {"login_role": "postgres", "effective_role": "postgres"},
        {"effective_role": "munim_owner"},  # SET ROLE after logging in as munim_app
    ],
)
def test_runtime_rejects_wrong_username(db_settings: Settings, change: dict) -> None:
    problems = runtime_identity_problems(replace(APP_OK, **change), db_settings)
    assert "unexpected_role(expected munim_app)" in problems


def test_runtime_rejects_wrong_database(db_settings: Settings) -> None:
    problems = runtime_identity_problems(replace(APP_OK, database="postgres"), db_settings)
    assert problems == ["unexpected_database(expected munim_ai)"]


def test_runtime_rejects_missing_identity(db_settings: Settings) -> None:
    assert runtime_identity_problems(None, db_settings) == ["identity_unavailable"]


def test_runtime_owner_role_is_rejected_as_a_whole(db_settings: Settings) -> None:
    """Pointing DATABASE_URL at munim_owner must not pass (the old check allowed it)."""
    problems = runtime_identity_problems(OWNER_OK, db_settings)
    assert {"unexpected_role(expected munim_app)", "inherit", "owns_database"} <= set(problems)


# --------------------------------------------------------------------------- migration rules
def test_migration_correct_role_and_database(db_settings: Settings) -> None:
    assert migration_identity_problems(OWNER_OK, db_settings) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            {"login_role": "munim_app", "effective_role": "munim_app", "owns_database": False},
            "unexpected_role(expected munim_owner)",
        ),
        (
            {"login_role": "postgres", "effective_role": "postgres"},
            "unexpected_role(expected munim_owner)",
        ),
        (
            {"database": "postgres", "owns_database": False},
            "unexpected_database(expected munim_ai)",
        ),
        ({"is_superuser": True}, "superuser"),
        ({"bypass_rls": True}, "bypassrls"),
        ({"owns_database": False}, "not_database_owner"),
    ],
)
def test_migration_rejects_wrong_identity(db_settings: Settings, change: dict, problem: str):
    assert problem in migration_identity_problems(replace(OWNER_OK, **change), db_settings)


def test_verify_migration_identity_passes_and_ends_its_transaction(db_settings: Settings) -> None:
    conn = _Connection(OWNER_OK)
    assert verify_migration_identity(conn, db_settings) == OWNER_OK
    assert conn.rolled_back, "identity query transaction must be closed before Alembic begins"


@pytest.mark.parametrize(
    "identity",
    [
        replace(OWNER_OK, login_role="munim_app", effective_role="munim_app"),
        replace(OWNER_OK, database="postgres"),
        replace(OWNER_OK, is_superuser=True),
        None,
    ],
)
def test_verify_migration_identity_fails_closed(db_settings: Settings, identity) -> None:
    conn = _Connection(identity)
    with pytest.raises(UnsafeDatabaseIdentityError) as exc_info:
        verify_migration_identity(conn, db_settings)
    assert conn.rolled_back
    message = str(exc_info.value)
    assert message.startswith("migration database connection failed the identity check")
    assert SENTINEL not in message
    assert "postgresql" not in message


def test_alembic_env_verifies_identity_before_configuring() -> None:
    """env.py must call verify_migration_identity before context.configure in online mode."""
    source = (Path(__file__).parents[1] / "alembic" / "env.py").read_text(encoding="utf-8")
    func = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "run_migrations_online"
    )
    calls = [
        (node.lineno, ast.unparse(node.func))
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
    ]
    verify_line = min(line for line, name in calls if name == "verify_migration_identity")
    configure_line = min(line for line, name in calls if name == "context.configure")
    assert verify_line < configure_line


# --------------------------------------------------------------------------- health check
def test_check_database_ok_for_correct_runtime_identity(db_settings, monkeypatch) -> None:
    monkeypatch.setattr(checks, "get_engine", lambda: _Engine(APP_OK))
    result = checks.check_database(db_settings)
    assert result.status is DatabaseStatus.OK
    assert result.role_check is RoleCheck.OK
    assert result.detail is None


@pytest.mark.parametrize(
    "identity",
    [
        replace(APP_OK, is_superuser=True),
        replace(APP_OK, bypass_rls=True),
        replace(APP_OK, inherit=True),
        replace(APP_OK, login_role="munim_owner", effective_role="munim_owner"),
        replace(APP_OK, database="postgres"),
    ],
)
def test_check_database_reports_unsafe_instead_of_passing(db_settings, monkeypatch, identity):
    monkeypatch.setattr(checks, "get_engine", lambda: _Engine(identity))
    result = checks.check_database(db_settings)
    assert result.status is DatabaseStatus.OK
    assert result.role_check is RoleCheck.UNSAFE
    assert result.detail and result.detail.startswith("unsafe connection: ")


def test_health_endpoint_degraded_for_unsafe_runtime_role(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checks, "get_engine", lambda: _Engine(replace(APP_OK, inherit=True)))
    body = client.get("/api/v1/health").json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["role_check"] == "unsafe"
    assert "inherit" in body["checks"]["database"]["detail"]


# --------------------------------------------------------------------------- configuration
def _assert_no_secret(exc: Exception) -> None:
    text = f"{exc}\n{exc!r}"
    assert SENTINEL not in text
    assert "postgresql+psycopg" not in text


def test_identical_database_urls_are_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, database_url=RUNTIME_URL, migration_database_url=RUNTIME_URL)
    assert "must not be identical" in str(exc_info.value)
    _assert_no_secret(exc_info.value)


def test_same_role_in_both_urls_is_rejected() -> None:
    other_db = RUNTIME_URL.replace("/munim_ai", "/postgres")
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, database_url=RUNTIME_URL, migration_database_url=other_db)
    assert "must use different roles" in str(exc_info.value)
    _assert_no_secret(exc_info.value)


def test_same_expected_role_names_are_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            database_url=RUNTIME_URL,
            migration_database_url=MIGRATION_URL,
            database_owner_role="munim_app",
        )
    assert "must be different roles" in str(exc_info.value)
    _assert_no_secret(exc_info.value)


def test_unparseable_url_error_has_no_secret() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            database_url=f"not a url {SENTINEL}",
            migration_database_url=MIGRATION_URL,
        )
    _assert_no_secret(exc_info.value)


def test_distinct_urls_and_roles_are_accepted(db_settings: Settings) -> None:
    assert db_settings.database_app_role == "munim_app"
    assert db_settings.database_owner_role == "munim_owner"
    assert db_settings.database_name == "munim_ai"
    assert SENTINEL not in repr(db_settings)


# --------------------------------------------------------------------------- no secrets in logs
def _formatted_logs(caplog: pytest.LogCaptureFixture) -> str:
    formatter = JsonFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)


def test_unsafe_identity_logs_contain_no_secrets(db_settings, monkeypatch, caplog) -> None:
    monkeypatch.setattr(checks, "get_engine", lambda: _Engine(replace(APP_OK, bypass_rls=True)))
    with caplog.at_level(logging.INFO):
        result = checks.check_database(db_settings)
    logs = _formatted_logs(caplog)
    assert "bypassrls" in logs
    assert SENTINEL not in logs
    assert "postgresql" not in logs
    assert SENTINEL not in result.model_dump_json()


def test_connection_failure_logs_and_response_contain_no_secrets(
    db_settings, monkeypatch, caplog
) -> None:
    # Simulate a driver error whose message embeds the full URL, password included.
    error = OperationalError("SELECT 1", {}, Exception(f"could not connect to {RUNTIME_URL}"))
    monkeypatch.setattr(checks, "get_engine", lambda: _Engine(error=error))
    with caplog.at_level(logging.INFO):
        result = checks.check_database(db_settings)
    assert result.status is DatabaseStatus.UNAVAILABLE
    logs = _formatted_logs(caplog)
    assert "OperationalError" in logs
    assert SENTINEL not in logs
    assert SENTINEL not in result.model_dump_json()
    for line in logs.splitlines():
        json.loads(line)  # still valid structured JSON
