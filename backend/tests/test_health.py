import pytest
from fastapi.testclient import TestClient

from app.schemas.health import DatabaseHealth, DatabaseStatus, RoleCheck


def test_health_without_database_is_ok_outside_production(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Munim AI API"
    assert body["environment"] == "test"
    assert body["version"]
    assert body["uptime_seconds"] >= 0
    assert body["checks"]["database"]["status"] == "not_configured"


def test_health_response_has_request_id_header(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "test-request-0001"})
    assert response.headers["X-Request-ID"] == "test-request-0001"


def test_unsafe_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "<script>"})
    assert response.headers["X-Request-ID"] != "<script>"
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize(
    ("database", "expected"),
    [
        (DatabaseHealth(status=DatabaseStatus.OK, role_check=RoleCheck.OK, latency_ms=1.0), "ok"),
        (DatabaseHealth(status=DatabaseStatus.UNAVAILABLE, detail="connection failed"), "degraded"),
        (DatabaseHealth(status=DatabaseStatus.OK, role_check=RoleCheck.UNSAFE), "degraded"),
    ],
)
def test_health_reflects_database_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    database: DatabaseHealth,
    expected: str,
) -> None:
    monkeypatch.setattr("app.services.health.check_database", lambda *_: database)

    body = client.get("/api/v1/health").json()

    assert body["status"] == expected
    assert body["checks"]["database"]["status"] == database.status.value


def test_health_does_not_leak_connection_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.health.check_database",
        lambda *_: DatabaseHealth(status=DatabaseStatus.UNAVAILABLE, detail="connection failed"),
    )
    text = client.get("/api/v1/health").text
    assert "postgresql" not in text
    assert "munim_app" not in text
