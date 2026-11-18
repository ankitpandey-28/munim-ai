import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import REDACTED, JsonFormatter, redact_text

SENTINEL_PHONE = "+91 98765 43210"


def _format(message: str, **extra: object) -> dict:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter().format(record))


@pytest.mark.parametrize(
    "raw",
    ["9876543210", "+919876543210", "+91 98765 43210", "09876543210", "91-9876543210"],
)
def test_phone_numbers_are_redacted(raw: str) -> None:
    assert raw not in redact_text(f"customer {raw} paid")


def test_non_phone_numbers_are_kept() -> None:
    assert redact_text("amount_paise 50000 for 12 items") == "amount_paise 50000 for 12 items"


def test_connection_string_password_redacted() -> None:
    out = redact_text("connect postgresql+psycopg://munim_app:s3cr3t@db:5432/munim")
    assert "s3cr3t" not in out
    assert "munim_app:[REDACTED]@db" in out


def test_bearer_token_and_wa_link_redacted() -> None:
    out = redact_text("Authorization: Bearer abc.def.ghi link https://wa.me/919876543210?text=hi")
    assert "abc.def.ghi" not in out
    assert "wa.me" not in out


def test_sensitive_extra_fields_redacted() -> None:
    payload = _format(
        "login attempt",
        password="hunter2",
        phone=SENTINEL_PHONE,
        refresh_token="tok",
        transcript="Ramesh ko 500 ka udhaar",
        shop_id="shop-123",
    )
    assert payload["password"] == REDACTED
    assert payload["phone"] == REDACTED
    assert payload["refresh_token"] == REDACTED
    assert payload["transcript"] == REDACTED
    assert payload["shop_id"] == "shop-123"


def test_nested_sensitive_fields_redacted() -> None:
    payload = _format("ctx", context={"user": {"password": "x", "role": "owner"}})
    assert payload["context"]["user"]["password"] == REDACTED
    assert payload["context"]["user"]["role"] == "owner"


def test_access_log_excludes_query_string(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.access"):
        client.get("/api/v1/health?phone=9876543210")

    records = [r for r in caplog.records if r.name == "app.access"]
    assert records, "expected an access log record"
    record = records[-1]
    assert record.path == "/api/v1/health"
    assert "9876543210" not in JsonFormatter().format(record)
