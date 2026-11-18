"""Structured logging with sensitive-data redaction (architecture §9.2 SV-8).

Rules:
- Logs carry identifiers (request id, later shop id / user id), never personal data.
- Structured ``extra`` fields whose names look sensitive are replaced with ``[REDACTED]``.
- Message text is scrubbed for Indian phone numbers, bearer tokens, connection-string
  passwords and wa.me links as a second line of defence.
- Request/response bodies are never logged by the framework layer.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import LogFormat, Settings
from app.core.request_context import get_request_id

REDACTED = "[REDACTED]"

SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "phone",
    "mobile",
    "transcript",
    "otp",
    "pin",
    "database_url",
    "dsn",
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Credentials embedded in URLs: scheme://user:password@host
    (
        re.compile(r"(?P<prefix>[a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s@]+:)[^@\s]+@"),
        r"\g<prefix>[REDACTED]@",
    ),
    # Authorization headers / bearer tokens
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    # WhatsApp deep links contain phone numbers and amounts
    (re.compile(r"(?i)https?://(?:api\.)?wa\.me/\S+"), "[REDACTED_WA_LINK]"),
    # Indian mobile numbers: optional +91/91/0 prefix, 10 digits starting 6-9
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), "[REDACTED_PHONE]"),
)

# Attributes present on every LogRecord; anything else came from ``extra=``.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(key: str, value: Any) -> Any:
    if is_sensitive_key(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(key, v) for v in value]
    return value


# Extras added by third-party libraries that carry no information (e.g. uvicorn's ANSI copy).
_IGNORED_EXTRAS = frozenset({"color_message"})


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: redact_value(key, value)
        for key, value in vars(record).items()
        if key not in _STANDARD_ATTRS and key not in _IGNORED_EXTRAS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        request_id = get_request_id()
        rid = f" [{request_id[:8]}]" if request_id else ""
        extras = _extra_fields(record)
        extra_text = " " + " ".join(f"{k}={v}" for k, v in extras.items()) if extras else ""
        line = f"{ts} {record.levelname:<7} {record.name}{rid}: {redact_text(record.getMessage())}"
        line += extra_text
        if record.exc_info:
            line += "\n" + redact_text(self.formatException(record.exc_info))
        return line


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_format is LogFormat.JSON else ConsoleFormatter()
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # Uvicorn's access log prints full URLs (query strings may carry personal data).
    # Our own middleware logs method, path, status and duration instead.
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True
