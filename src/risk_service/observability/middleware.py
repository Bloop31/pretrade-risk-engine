"""ASGI middleware: request IDs and HTTP metrics.

Written as plain ASGI rather than ``BaseHTTPMiddleware`` to avoid the extra
task and body buffering that the latter adds to every request.
"""

import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.contextvars import bound_contextvars

from risk_service.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS

REQUEST_ID_HEADER = "x-request-id"
# Accept caller-supplied IDs only if they are short and safe to put in logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id(scope: Scope) -> str:
    for key, value in scope.get("headers", ()):
        if key == REQUEST_ID_HEADER.encode():
            candidate: str = value.decode("latin-1")
            if _VALID_REQUEST_ID.match(candidate):
                return candidate
            break
    return uuid.uuid4().hex


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            with bound_contextvars(request_id=request_id):
                await self.app(scope, receive, send_wrapper)
        finally:
            # FastAPI stores the matched route in the scope once routing has run.
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"]
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
            HTTP_LATENCY.labels(method=method, route=route).observe(time.perf_counter() - start)
