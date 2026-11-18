import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_requires_database_url() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", database_url=None)


def test_database_url_is_secret() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://munim_app:s3cr3t@localhost/munim"
    )
    assert "s3cr3t" not in repr(settings)
    assert "s3cr3t" not in str(settings.model_dump())


def test_docs_disabled_in_production() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://u:p@127.0.0.1:1/x",
        auth_secret_key="k" * 40,
        frontend_origins="https://munim.example",
    )
    # Startup checks would (correctly) refuse to start without a reachable database.
    with TestClient(create_app(settings, startup_checks=False)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth_secret_key": None},
        {"auth_secret_key": "too-short"},
        {"session_cookie_secure": False},
        {"frontend_origins": "http://insecure.example"},
        {"frontend_origins": ""},
    ],
)
def test_production_rejects_unsafe_security_config(overrides: dict) -> None:
    base = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/x",
        "auth_secret_key": "k" * 40,
        "frontend_origins": "https://munim.example",
    }
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **(base | overrides))
    assert "k" * 40 not in str(exc_info.value)
