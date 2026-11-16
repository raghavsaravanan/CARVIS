"""Operator-gated, size-capped PDF uploads for ``/upload`` (M2 Track A2).

``/upload`` can trigger paid LlamaParse work, so every request must present the operator token in
``X-Carvis-Operator-Token``. The token is compared in constant time against
``CARVIS_OPERATOR_TOKEN``; when the variable is unset or blank every upload is rejected (fails
closed). Authentication and the declared ``Content-Length`` are checked by :class:`OperatorUploadRoute`
before FastAPI reads any body byte, and the body is then counted as it streams so a request without
``Content-Length`` (or one that lies about it) stops at the cap instead of filling the disk.

The file itself must start with the ``%PDF-`` magic and be at most :data:`MAX_UPLOAD_BYTES`; the
route checks both before it schedules ingestion, so no rejected request reaches LlamaParse.
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Callable, Coroutine

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.types import Message, Receive

OPERATOR_TOKEN_ENV = "CARVIS_OPERATOR_TOKEN"
OPERATOR_TOKEN_HEADER = "x-carvis-operator-token"

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
"""Largest accepted PDF (50 MiB)."""

MULTIPART_ENVELOPE_BYTES = 64 * 1024
"""Allowance for multipart boundaries, part headers and the small vehicle form fields."""

MAX_UPLOAD_BODY_BYTES = MAX_UPLOAD_BYTES + MULTIPART_ENVELOPE_BYTES
"""Largest accepted request body; the exact file cap is enforced when the file is copied."""

PDF_MAGIC = b"%PDF-"

UNAUTHORIZED = {"detail": "Unauthorized"}
TOO_LARGE_DETAIL = f"PDF must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB or smaller."
NOT_A_PDF_DETAIL = "Uploaded file is not a valid PDF."


def configured_operator_token() -> str:
    """The configured operator token, stripped; empty when unset or blank."""
    return (os.getenv(OPERATOR_TOKEN_ENV) or "").strip()


def operator_request_authorized(presented: str | None) -> bool:
    """Constant-time check of the presented header against the configured operator token.

    Fails closed: no configured token, or no presented value, is never authorized.
    """
    expected = configured_operator_token()
    if not expected or presented is None:
        return False
    # Compare bytes: compare_digest raises TypeError on non-ASCII str input, and an
    # attacker-controlled header must produce a 401, never a 500. ASGI servers decode header bytes
    # as latin-1, so encoding back with latin-1 recovers exactly the bytes the client sent.
    return hmac.compare_digest(
        presented.encode("latin-1", "replace"),
        expected.encode("utf-8", "surrogateescape"),
    )


def _declared_length(request: Request) -> int | None:
    """Parsed ``Content-Length``; ``None`` when absent, ``-1`` when malformed."""
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    raw = raw.strip()
    return int(raw) if raw.isascii() and raw.isdigit() else -1


def limited_receive(receive: Receive, limit: int) -> Receive:
    """Wrap an ASGI ``receive`` so the request body cannot exceed ``limit`` bytes."""
    received = 0

    async def wrapped() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit:
                # FastAPI re-raises HTTPException from body parsing, so this becomes a 413 and the
                # multipart parser closes its spooled files.
                raise HTTPException(status_code=413, detail=TOO_LARGE_DETAIL)
        return message

    return wrapped


class OperatorUploadRoute(APIRoute):
    """Route class that authenticates and size-checks before the body is parsed.

    FastAPI parses ``File``/``Form`` parameters, spooling the whole upload to disk, before it runs
    any dependency. Doing these checks here instead means an unauthenticated or declared-oversized
    request is answered without reading its body.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            presented = request.headers.getlist(OPERATOR_TOKEN_HEADER)
            # Exactly one token header: a duplicate is ambiguous across proxies, so it fails closed.
            if len(presented) != 1 or not operator_request_authorized(presented[0]):
                return JSONResponse(status_code=401, content=UNAUTHORIZED)
            declared = _declared_length(request)
            if declared == -1:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
            if declared is not None and declared > MAX_UPLOAD_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": TOO_LARGE_DETAIL})
            limited = Request(request.scope, receive=limited_receive(request.receive, MAX_UPLOAD_BODY_BYTES))
            return await handler(limited)

        return guarded
