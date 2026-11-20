"""Per-route request body caps for the Carvis API (M2 Track A6).

Starlette and FastAPI read a whole request body (spooling multipart uploads to disk) before a
handler runs, so a handler-level ``len()`` check bounds only what the handler looks at, not what the
server accepts. :class:`BodyLimitedRoute` caps the body itself:

- The declared ``Content-Length`` is checked when the body is first read, and the body is counted as
  it streams, so a request with no ``Content-Length``, or one that understates it, stops at the cap.
- The check is lazy: a handler that authenticates before reading the body (such as ``/vapi-tool``)
  still answers an unauthenticated request with its own 401, without reading a byte. Routes whose
  parameters FastAPI parses from the body (multipart and JSON-model routes) read it before their
  handler authenticates, so an over-cap unauthenticated request to them gets 413, not 401.
- Once the cap is exceeded the route answers ``413`` with the path's detail, even when the handler
  catches the error itself (``/vapi-tool`` wraps ``request.json()`` in a broad ``except``).
- Rejections, and any response sent without reading an announced body, carry
  ``Connection: close`` so the server does not keep reading and discarding the rest on keep-alive.

This is an application-level cap: the ASGI server still receives what the client sends before the
connection closes. Uvicorn itself answers a malformed ``Content-Length`` with a plain-text 400 before
the app runs; the JSON 400 here covers servers that do not. Response shapes are FastAPI's existing
``{"detail": ...}``; no contract changes. ``/upload`` keeps its own
:class:`upload_security.OperatorUploadRoute`, which authenticates before applying the same idea.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.types import Message, Receive

KiB = 1024
MiB = 1024 * KiB

MULTIPART_ENVELOPE_BYTES = 64 * KiB
"""Allowance for multipart boundaries, part headers and small form fields beside a file."""

DEFAULT_BODY_LIMIT_BYTES = 64 * KiB
"""Cap for routes not listed in a route's limits: small JSON bodies such as conversation commands."""

TOO_LARGE_DETAIL = "Request body is too large."
CLOSE_CONNECTION = {"connection": "close"}
INVALID_LENGTH_DETAIL = "Invalid Content-Length."


@dataclass(frozen=True)
class BodyLimit:
    max_bytes: int
    detail: str = TOO_LARGE_DETAIL


class _BodyRejected(HTTPException):
    """Raised from ``receive``; FastAPI re-raises HTTPException from body parsing unchanged."""


def _declared_length(request: Request) -> int | None:
    """Parsed ``Content-Length``; ``None`` when absent, ``-1`` when malformed."""
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    raw = raw.strip()
    return int(raw) if raw.isascii() and raw.isdigit() else -1


def _announces_body(request: Request) -> bool:
    length = _declared_length(request)
    return bool(length) or "chunked" in request.headers.get("transfer-encoding", "").lower()


def limited_receive(request: Request, limit: BodyLimit, outcome: dict[str, Any]) -> Receive:
    """Wrap ``request.receive`` so the body cannot exceed ``limit``; record a rejection in ``outcome``."""
    receive = request.receive
    received = 0
    checked = False

    def reject(status: int, detail: str) -> _BodyRejected:
        # Connection: close stops the server draining the rest of a rejected body on keep-alive.
        outcome.setdefault("response", JSONResponse(status_code=status, content={"detail": detail},
                                                    headers=CLOSE_CONNECTION))
        return _BodyRejected(status_code=status, detail=detail)

    async def wrapped() -> Message:
        nonlocal received, checked
        if "response" in outcome:
            # Already rejected: never pull more of an oversized body from the client.
            raise reject(413, limit.detail)
        if not checked:
            checked = True
            declared = _declared_length(request)
            if declared == -1:
                raise reject(400, INVALID_LENGTH_DETAIL)
            if declared is not None and declared > limit.max_bytes:
                raise reject(413, limit.detail)
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit.max_bytes:
                raise reject(413, limit.detail)
            if not message.get("more_body", False):
                outcome["body_complete"] = True
        return message

    return wrapped


def body_limited_route(limits: dict[str, BodyLimit], default: BodyLimit) -> type[APIRoute]:
    """An ``APIRoute`` class that caps each route's body by its path template."""

    class BodyLimitedRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()
            limit = limits.get(self.path, default)

            async def guarded(request: Request) -> Response:
                outcome: dict[str, Any] = {}
                limited = Request(request.scope, receive=limited_receive(request, limit, outcome))
                try:
                    response = await handler(limited)
                except Exception:
                    # The rejection, or whatever a handler raised after catching it.
                    if "response" in outcome:
                        return outcome["response"]
                    raise
                # A handler that swallowed the rejection must not answer as if the body were fine.
                if "response" in outcome:
                    return outcome["response"]
                if _announces_body(request) and not outcome.get("body_complete"):
                    # Answered without reading the announced body (an unauthenticated /vapi-tool
                    # request, say): close, so the server does not drain it on keep-alive.
                    response.headers.update(CLOSE_CONNECTION)
                return response

            return guarded

    return BodyLimitedRoute
