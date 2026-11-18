from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.database.session import get_engine, get_session_factory
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests never read a developer's local backend/.env.
    return Settings(_env_file=None, app_env="test", log_format="json", database_url=None)


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.database.session.get_settings", lambda: settings)
    app = create_app(settings, startup_checks=False)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    get_engine.cache_clear()
    get_session_factory.cache_clear()
