from fastapi.testclient import TestClient
from pydantic import BaseModel


def test_unknown_route_returns_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    class Payload(BaseModel):
        phone: str
        password: str
        age: int

    app = client.app

    @app.post("/_test/validate")  # type: ignore[attr-defined]
    def validate(payload: Payload) -> dict[str, str]:
        return {"ok": "yes"}

    response = client.post(
        "/_test/validate",
        json={"phone": "9876543210", "password": "hunter2-secret", "age": "not-a-number"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "hunter2-secret" not in response.text
    assert "9876543210" not in response.text
    assert "not-a-number" not in response.text


def test_unhandled_exception_returns_generic_500(client: TestClient) -> None:
    app = client.app

    @app.get("/_test/boom")  # type: ignore[attr-defined]
    def boom() -> None:
        raise RuntimeError("internal detail: password=hunter2")

    response = client.get("/_test/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text
