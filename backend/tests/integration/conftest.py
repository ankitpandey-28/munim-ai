"""Integration fixtures: a disposable PostgreSQL cluster with the real migrations applied.

Never connects to the developer's real database: the cluster is created by ``initdb`` in a
temporary directory on a free port (tests/support/pg_cluster.py) and deleted afterwards.
SQLite is never used as a substitute: RLS, grants and triggers need real PostgreSQL.

If PostgreSQL binaries are not found the tests are skipped, unless MUNIM_REQUIRE_PG=1 (CI),
in which case they fail.
"""

import itertools
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app.core.config import Settings, get_settings
from app.database.session import get_engine, get_session_factory
from app.main import create_app
from app.modules.identity.service import registration_limiter
from tests.support.pg_cluster import TempPostgres, find_pg_bin

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_AUTH_KEY = "integration-test-hmac-key-0123456789abcdef"
STRONG_PASSWORD = "Kirana-Test-Pass-91"
_phones = itertools.count(1)


def next_phone() -> str:
    """Unique valid Indian mobile numbers per test run (no cleanup needed)."""
    return f"+9190{next(_phones):08d}"


def run_alembic(pg: TempPostgres, *args: str) -> subprocess.CompletedProcess:
    env = pg.alembic_env()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    exe = Path(sys.executable).with_name("alembic.exe" if os.name == "nt" else "alembic")
    with tempfile.TemporaryDirectory() as cwd:  # never read backend/.env
        return subprocess.run(
            [str(exe), "-c", str(BACKEND_DIR / "alembic.ini"), *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture(scope="session")
def pg() -> Iterator[TempPostgres]:
    bin_dir = find_pg_bin()
    if bin_dir is None:
        message = "PostgreSQL binaries not found (set MUNIM_PG_BIN to the PostgreSQL bin dir)"
        if os.environ.get("MUNIM_REQUIRE_PG") == "1":
            pytest.fail(message)
        pytest.skip(message)
    cluster = TempPostgres(bin_dir).start()
    try:
        result = run_alembic(cluster, "upgrade", "head")
        if result.returncode != 0:
            output = result.stdout + result.stderr
            for secret in (cluster.owner_password, cluster.app_password):
                output = output.replace(secret, "***")
            pytest.fail(f"alembic upgrade failed:\n{output[-3000:]}")
        yield cluster
    finally:
        cluster.stop()


@pytest.fixture
def settings(pg: TempPostgres) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        log_format="json",
        database_url=pg.app_url,
        migration_database_url=pg.owner_url,
        auth_secret_key=TEST_AUTH_KEY,
        # TestClient talks plain http to "testserver"; the Secure default is tested separately.
        session_cookie_secure=False,
        frontend_origins="http://testserver",
        login_ip_max_attempts=1000,  # IP throttling has its own test
        registration_ip_max_per_hour=1000,
    )


def _make_client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.database.session.get_settings", lambda: settings)
    monkeypatch.setattr("app.core.security.get_settings", lambda: settings)
    registration_limiter.reset()
    app = create_app(settings)  # startup identity check runs against the disposable DB
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def make_client(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    clients: list[TestClient] = []

    def factory(custom: Settings | None = None) -> TestClient:
        client = _make_client(custom or settings, monkeypatch)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture(scope="session")
def app_engine(pg: TempPostgres) -> Iterator[Engine]:
    """Direct connection as the runtime role munim_app (subject to RLS and grants)."""
    engine = create_engine(pg.app_url, pool_size=2)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def owner_engine(pg: TempPostgres) -> Iterator[Engine]:
    """Direct connection as the schema owner munim_owner (FORCE RLS applies to it too)."""
    engine = create_engine(pg.owner_url, pool_size=2)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def super_engine(pg: TempPostgres) -> Iterator[Engine]:
    """Throwaway superuser, used ONLY to arrange test data (e.g. expire a session)."""
    engine = create_engine(pg.superuser_url.replace("/munim_ai", "/munim_ai"), pool_size=2)
    yield engine
    engine.dispose()


# ----------------------------------------------------------------------------- API helpers
def register(client: TestClient, phone: str | None = None, name: str = "Ramesh Kumar") -> dict:
    phone = phone or next_phone()
    response = client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "name": name, "password": STRONG_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return {"phone": phone, "body": response.json()}


def create_shop(client: TestClient, name: str = "Sharma Kirana", key: str | None = None) -> dict:
    response = client.post(
        "/api/v1/shops",
        json={"name": name, "city": "Ludhiana"},
        headers={"Idempotency-Key": key or os.urandom(12).hex()},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def owner(make_client) -> dict:
    """A registered owner with one shop; returns client + ids."""
    client = make_client()
    user = register(client)
    shop = create_shop(client)
    return {
        "client": client,
        "phone": user["phone"],
        "user_id": user["body"]["user"]["id"],
        "shop_id": shop["shop"]["id"],
    }
