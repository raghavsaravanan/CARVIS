"""``GET /v1/me`` and ``GET /v1/workspaces`` (M2 B2c; contract: ``docs/architecture/05-api-v1.md``).

Both routes are user-scoped: they read only the caller's own user row and memberships, inside the tenant unit of
work (RLS second layer) and with an explicit application filter on the caller's user ID. Caller-supplied
identifiers (``user_id``, ``workspace_id``, ``shop_id``, ``X-Workspace-Id``) are ignored. Timestamps are UTC,
``YYYY-MM-DDTHH:MM:SSZ``. The workspace cursor is opaque to clients (base64url of the last item's 16 ID bytes).
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.types import Integer, Uuid

from api_v1.auth import Caller, current_caller, tenant
from api_v1.errors import PREFIX, SERVER_ERROR, VALIDATION_FAILED, ApiError, ErrorEnvelope, v1_route_class
from request_limits import DEFAULT_BODY_LIMIT_BYTES, BodyLimit

DEFAULT_LIMIT = 25
MAX_LIMIT = 100

_ERRORS = {401: {"model": ErrorEnvelope, "description": "Missing or unacceptable credentials"},
           500: {"model": ErrorEnvelope, "description": "Unexpected error"},
           503: {"model": ErrorEnvelope, "description": "Temporarily unavailable (retryable)"}}
_ERRORS_WITH_QUERY = {**_ERRORS, 422: {"model": ErrorEnvelope, "description": "Invalid parameters"}}

# Router-level: every /v1 route requires the caller; FastAPI runs the dependency once per request.
router = APIRouter(prefix=PREFIX, dependencies=[Depends(current_caller)],
                   route_class=v1_route_class({}, BodyLimit(DEFAULT_BODY_LIMIT_BYTES)))

ME_QUERY = text("SELECT u.id, u.email, u.display_name, u.created_at FROM carvis.users AS u "
                "WHERE u.id = :user_id").bindparams(bindparam("user_id", type_=Uuid))
_WORKSPACES = ("SELECT w.id, w.kind, w.name, m.role, w.created_at FROM carvis.memberships AS m "
               "JOIN carvis.workspaces AS w ON w.id = m.workspace_id WHERE m.user_id = :user_id{after} "
               "ORDER BY w.id LIMIT :rows")
WORKSPACES_QUERY = text(_WORKSPACES.format(after="")).bindparams(
    bindparam("user_id", type_=Uuid), bindparam("rows", type_=Integer))
WORKSPACES_AFTER_QUERY = text(_WORKSPACES.format(after=" AND w.id > :after")).bindparams(
    bindparam("user_id", type_=Uuid), bindparam("after", type_=Uuid), bindparam("rows", type_=Integer))


def utc_timestamp(value: datetime) -> str:
    """The frozen ``/v1`` timestamp form, whatever the session ``TimeZone``: UTC, whole seconds, ``Z``."""
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encode_cursor(workspace_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(workspace_id.bytes).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> uuid.UUID:
    """The workspace ID inside an opaque cursor, or 422. Never authority: it only bounds the caller's own rows."""
    if len(cursor) != 22 or not cursor.isascii():
        raise ApiError(VALIDATION_FAILED, "invalid_parameter")
    try:
        raw = base64.urlsafe_b64decode(cursor + "==")
    except (binascii.Error, ValueError):
        raise ApiError(VALIDATION_FAILED, "invalid_parameter") from None
    if len(raw) != 16 or encode_cursor(uuid.UUID(bytes=raw)) != cursor:
        raise ApiError(VALIDATION_FAILED, "invalid_parameter")
    return uuid.UUID(bytes=raw)


class Me(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    created_at: str


class Workspace(BaseModel):
    id: uuid.UUID
    kind: Literal["personal", "shop"]
    name: str
    role: Literal["owner", "admin", "member"]
    created_at: str


class WorkspacePage(BaseModel):
    items: list[Workspace]
    next_cursor: str | None


@router.get("/me", response_model=Me, responses=_ERRORS, operation_id="get_me", summary="The caller's profile")
async def get_me(request: Request, caller: Caller = Depends(current_caller)) -> Me:
    async with tenant(request, caller) as session:
        rows = (await session.execute(ME_QUERY, {"user_id": caller.user.user_id})).all()
    if len(rows) != 1:
        raise ApiError(SERVER_ERROR, "unhandled_error")  # the context invariant is broken; never guess a row
    row = rows[0]
    return Me(id=row.id, email=row.email, display_name=row.display_name, created_at=utc_timestamp(row.created_at))


@router.get("/workspaces", response_model=WorkspacePage, responses=_ERRORS_WITH_QUERY,
            operation_id="list_workspaces", summary="The caller's workspace memberships")
async def list_workspaces(request: Request, caller: Caller = Depends(current_caller),
                          limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
                          cursor: str | None = Query(None, max_length=64)) -> WorkspacePage:
    after = decode_cursor(cursor) if cursor is not None else None
    params = {"user_id": caller.user.user_id, "rows": limit + 1}
    async with tenant(request, caller) as session:
        if after is None:
            rows = (await session.execute(WORKSPACES_QUERY, params)).all()
        else:
            rows = (await session.execute(WORKSPACES_AFTER_QUERY, {**params, "after": after})).all()
    page = rows[:limit]
    items = [Workspace(id=row.id, kind=row.kind, name=row.name, role=row.role,
                       created_at=utc_timestamp(row.created_at)) for row in page]
    next_cursor = encode_cursor(page[-1].id) if len(rows) > limit else None
    return WorkspacePage(items=items, next_cursor=next_cursor)
