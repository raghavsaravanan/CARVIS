"""The ``/v1`` error envelope (M2 B2c, ADR-0004; contract: ``docs/architecture/05-api-v1.md``).

Every error the application produces for a ``/v1`` path is
``{"error": {"code", "message", "request_id", "retryable"}}``. ``request_id`` is the response's ``X-Request-ID``
(B1). Messages are fixed per code: never exception text, token data or caller input. Legacy paths keep FastAPI's
own shapes, byte for byte.

Mechanisms:

- :func:`http_exception_handler` and :func:`validation_exception_handler` are the app-wide handlers for
  Starlette ``HTTPException`` (router 404/405 included) and ``RequestValidationError``; they answer with the
  envelope on ``/v1`` paths and delegate to FastAPI's defaults elsewhere.
- :class:`V1Route` is the ``/v1`` router's route class: body limited (A6) with envelope rejections; it converts
  :class:`ApiError` to the envelope, re-raises ``HTTPException`` and ``RequestValidationError`` to the handlers,
  and turns any other exception into a 500 (logged by type name only). An app-wide ``Exception`` handler is not
  used because Starlette installs it outside ``RequestIdMiddleware``.
- :class:`V1HeadersMiddleware` puts ``Cache-Control: no-store`` on every ``/v1`` response, redirects included.

Responses the ASGI server generates before the application runs (for example Uvicorn's plain-text 400 for a
malformed request) cannot carry the envelope, the request ID or ``no-store``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from fastapi import Request, Response
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.exception_handlers import request_validation_exception_handler as default_validation_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from log_config import log_event, register_values
from request_limits import BodyLimit, body_limited_route

logger = logging.getLogger("carvis.v1")

PREFIX = "/v1"
NO_STORE = "no-store"


@dataclass(frozen=True)
class ErrorCode:
    code: str
    status: int
    retryable: bool
    message: str


UNAUTHORIZED = ErrorCode("unauthorized", 401, False, "Authentication is required.")
FORBIDDEN = ErrorCode("forbidden", 403, False, "This action is not allowed.")
NOT_FOUND = ErrorCode("not_found", 404, False, "The requested resource was not found.")
METHOD_NOT_ALLOWED = ErrorCode("method_not_allowed", 405, False, "The method is not allowed for this resource.")
PAYLOAD_TOO_LARGE = ErrorCode("payload_too_large", 413, False, "The request body is too large.")
VALIDATION_FAILED = ErrorCode("validation_failed", 422, False, "The request is not valid.")
UNSUPPORTED_CLIENT = ErrorCode("unsupported_client", 426, False, "This app version is no longer supported.")
RATE_LIMITED = ErrorCode("rate_limited", 429, True, "Too many requests. Try again later.")
SERVER_ERROR = ErrorCode("server_error", 500, False, "An unexpected error occurred.")
SERVICE_UNAVAILABLE = ErrorCode("service_unavailable", 503, True, "The service is temporarily unavailable.")

CODES = (UNAUTHORIZED, FORBIDDEN, NOT_FOUND, METHOD_NOT_ALLOWED, PAYLOAD_TOO_LARGE, VALIDATION_FAILED,
         UNSUPPORTED_CLIENT, RATE_LIMITED, SERVER_ERROR, SERVICE_UNAVAILABLE)
_BY_STATUS = {code.status: code for code in CODES}

# Reason codes are for logs only, never for the response body.
REASONS = ("v1_not_started", "auth_unconfigured", "database_unconfigured", "missing_credentials",
           "invalid_credentials", "token_rejected", "auth_unavailable", "login_unsafe", "database_unavailable",
           "request_deadline", "inactive_user", "invalid_parameter", "unhandled_error")
register_values("reason", REASONS)


class ApiError(Exception):
    """An error a ``/v1`` route or dependency raises deliberately; ``reason`` is logged, never sent."""

    def __init__(self, error: ErrorCode, reason: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(reason)
        self.error = error
        self.reason = reason
        self.headers = headers or {}


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def is_v1_path(path: str) -> bool:
    return path == PREFIX or path.startswith(PREFIX + "/")


def request_id_of(request: Request) -> str:
    """The request's B1 ID (set by ``RequestIdMiddleware``); a fresh one only if the middleware did not run."""
    value = request.scope.get("state", {}).get("request_id")
    return value if isinstance(value, str) and value else uuid.uuid4().hex


def code_for_status(status: int) -> ErrorCode:
    if status in _BY_STATUS:
        return _BY_STATUS[status]
    if 400 <= status < 500:
        return ErrorCode(VALIDATION_FAILED.code, status, False, VALIDATION_FAILED.message)
    return ErrorCode(SERVER_ERROR.code, status, False, SERVER_ERROR.message)


def envelope_response(request: Request, error: ErrorCode, headers: dict[str, str] | None = None) -> JSONResponse:
    body = {"error": {"code": error.code, "message": error.message, "request_id": request_id_of(request),
                      "retryable": error.retryable}}
    return JSONResponse(body, status_code=error.status, headers={**(headers or {}), "cache-control": NO_STORE})


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    if not is_v1_path(request.url.path):
        return await default_http_exception_handler(request, exc)
    return envelope_response(request, code_for_status(exc.status_code), dict(exc.headers or {}))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
    if not is_v1_path(request.url.path):
        return await default_validation_handler(request, exc)
    return envelope_response(request, VALIDATION_FAILED)  # never echoes the input


def _rejection(status: int, detail: str, request: Request, headers: dict[str, str]) -> Response:
    return envelope_response(request, code_for_status(status), headers)


def v1_route_class(limits: dict[str, BodyLimit], default: BodyLimit):
    """The ``/v1`` route class: A6 body limits with envelope rejections, and the exception precedence above."""
    base = body_limited_route(limits, default, rejection=_rejection)

    class V1Route(base):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def enveloped(request: Request) -> Response:
                try:
                    return await handler(request)
                except ApiError as exc:
                    log_event(logger, logging.INFO, "v1_request_refused", code=exc.error.code, reason=exc.reason)
                    return envelope_response(request, exc.error, exc.headers)
                except (StarletteHTTPException, RequestValidationError):
                    raise
                except Exception as exc:  # noqa: BLE001 - any other failure is a generic 500, type name only
                    log_event(logger, logging.ERROR, "v1_unhandled_error", code=SERVER_ERROR.code,
                              reason="unhandled_error", error=type(exc).__name__)
                    return envelope_response(request, SERVER_ERROR)

            return enveloped

    return V1Route


class V1HeadersMiddleware:
    """Pure ASGI: ``Cache-Control: no-store`` on every response to a ``/v1`` path (redirects and 404/405 too)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not is_v1_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = [(name, value) for name, value in message.get("headers", [])
                           if name.lower() != b"cache-control"]
                message = {**message, "headers": [*headers, (b"cache-control", NO_STORE.encode("ascii"))]}
            await send(message)

        await self.app(scope, receive, send_no_store)


def install(app) -> None:
    """Install the ``/v1``-scoped handlers and the header middleware on ``app``."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_middleware(V1HeadersMiddleware)
