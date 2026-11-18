"""Request middleware: request id propagation and access logging without personal data."""

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import (
    REQUEST_ID_HEADER,
    new_request_id,
    reset_request_id,
    set_request_id,
)

access_logger = logging.getLogger("app.access")


class RequestContextMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware) so context vars flow to handlers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name == REQUEST_ID_HEADER.lower().encode():
                incoming = value.decode("latin-1")
                break
        request_id = new_request_id(incoming)
        token = set_request_id(request_id)
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Path only: query strings are never logged.
            access_logger.info(
                "request completed",
                extra={
                    "http_method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            reset_request_id(token)


UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginCheckMiddleware:
    """CSRF defence for cookie-authenticated requests (architecture §6.3).

    Browsers attach an ``Origin`` header to state-changing requests. If present, it must be one
    of the configured frontend origins; otherwise the request is rejected before routing.
    Requests without an Origin header (non-browser clients) are allowed, because a forged
    cross-site browser request always carries one. The session cookie is also SameSite=Strict.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {o.rstrip("/") for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") in UNSAFE_METHODS:
            origin = None
            for name, value in scope.get("headers", []):
                if name == b"origin":
                    origin = value.decode("latin-1").rstrip("/")
                    break
            if origin is not None and origin not in self.allowed:
                from app.core.errors import _error_response

                response = _error_response(
                    403, "ORIGIN_NOT_ALLOWED", "Request origin is not allowed."
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
