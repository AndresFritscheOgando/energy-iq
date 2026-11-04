"""Pure ASGI middleware: request context and body size limit (spec 0008).

Pure ASGI instead of ``BaseHTTPMiddleware`` so streamed bodies are counted as
they arrive and the 500 path can be owned outside every handler.
"""

import logging
import re
import time
from uuid import uuid4

from fastapi.routing import APIRoute
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from energyiq.platform.http.problems import problem_response, request_id_from
from energyiq.platform.logging import ACCESS_LOGGER, ERROR_LOGGER

REQUEST_ID_HEADER = "X-Request-ID"
CLIENT_CLOSED_REQUEST = 499
_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}", re.ASCII)
_CONTENT_LENGTH = re.compile(r"[0-9]+", re.ASCII)

_access_log = logging.getLogger(ACCESS_LOGGER)
_error_log = logging.getLogger(ERROR_LOGGER)


def _client_request_id(scope: Scope) -> str | None:
    value = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if value is not None and _REQUEST_ID.fullmatch(value):
        return value
    return None


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    return route.path if isinstance(route, APIRoute) else "unmatched"


class RequestContextMiddleware:
    """Request id, one access log line, and the only 500 path.

    Every exception from inner layers is caught here: the traceback is logged
    once with the request id, a 500 problem is sent if the response has not
    started, and nothing is re raised. On a client disconnect before the
    response starts, nothing is sent and the access status is 499.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _client_request_id(scope) or str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        response_started = False
        disconnected = False
        status = 500

        async def tracking_receive() -> Message:
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect" and not response_started:
                disconnected = True
            return message

        async def tagging_send(message: Message) -> None:
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                if disconnected:
                    status = CLIENT_CLOSED_REQUEST
                    return
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            elif disconnected and not response_started:
                return
            await send(message)

        try:
            await self.app(scope, tracking_receive, tagging_send)
        except Exception:  # noqa: BLE001 - this layer owns every unhandled error
            _error_log.exception(
                "unhandled exception", extra={"request_id": request_id}
            )
            if disconnected and not response_started:
                status = CLIENT_CLOSED_REQUEST
            elif not response_started:
                status = 500
                response = problem_response(
                    500,
                    "internal_error",
                    request_id,
                    headers={REQUEST_ID_HEADER: request_id},
                )
                await response(scope, receive, send)
        finally:
            if disconnected and not response_started:
                status = CLIENT_CLOSED_REQUEST
            _access_log.info(
                "request",
                extra={
                    "access": {
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": _route_template(scope),
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
                },
            )


class BodySizeLimitMiddleware:
    """Reject bodies over ``max_bytes``, declared or streamed (AC-9).

    A declared ``Content-Length`` is checked before the app runs. A streamed
    body raises ``HTTPException(413)`` from ``receive`` once the running count
    passes the cap; FastAPI re raises that instead of wrapping it as 400.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            if not _CONTENT_LENGTH.fullmatch(declared.strip()):
                response = problem_response(
                    400, "invalid_content_length", request_id_from(scope)
                )
                await response(scope, receive, send)
                return
            if int(declared) > self.max_bytes:
                response = problem_response(
                    413, "payload_too_large", request_id_from(scope)
                )
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(413)
            return message

        await self.app(scope, limited_receive, send)
