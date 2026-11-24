"""The ``/v1`` authentication dependency and request runtime (M2 B2c; ADR-0002, ADR-0003, doc 04).

Every ``/v1`` request passes :func:`current_caller` (a router-level dependency), in this order, each step fail-closed:

1. no runtime (lifespan not run) ⇒ 503; 2. issuer settings unset ⇒ 503 (ADR-0002 transitional rule);
3. database URL unset ⇒ 503;
4. bearer credential from the raw headers: none ⇒ 401 ``WWW-Authenticate: Bearer``; anything unacceptable ⇒
   401 ``Bearer error="invalid_token"``;
5. :meth:`auth.tokens.TokenVerifier.verify`: ``InvalidToken`` ⇒ 401; ``AuthUnavailable`` (no usable keys) ⇒ 503;
6. outside local, the runtime-login check on first use (:class:`LoginGate`) ⇒ 503 while it fails;
7. bootstrap transaction (:func:`db.context.provision`); 8. a non-active user ⇒ 401, no tenant transaction;
9. the route's tenant unit of work (:func:`tenant`).

Steps 6–9 share one deadline (:data:`REQUEST_DATABASE_DEADLINE_SECONDS`); expiry or any database error ⇒ 503.
Reason codes go to logs only. Tokens, emails and exception messages are never logged or returned.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from fastapi import Request, Security
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api_v1.errors import SERVICE_UNAVAILABLE, UNAUTHORIZED, ApiError
from auth.jwks import AuthUnavailable
from auth.tokens import MAX_TOKEN_BYTES, InvalidToken, Principal
from db.context import BootstrapContext, ProvisionedUser, provision, tenant_session

REQUEST_DATABASE_DEADLINE_SECONDS = 5.0
LOGIN_CHECK_DEADLINE_SECONDS = 2.0
GATE_STATEMENT_TIMEOUT_MS = 1500
GATE_LOCK_TIMEOUT_MS = 500

AUTHORIZATION = b"authorization"
CHALLENGE = {"www-authenticate": "Bearer"}
INVALID_TOKEN_CHALLENGE = {"www-authenticate": 'Bearer error="invalid_token"'}
# RFC 6750 §2.1 credentials: "Bearer" 1*SP b64token; auth-scheme is case-insensitive (RFC 9110 §11.1).
_BEARER = re.compile(r"(?i:bearer) +([A-Za-z0-9\-._~+/]+=*)")
_BEARER_SCHEME = re.compile(r"(?i:bearer)(?:\s.*)?", re.DOTALL)
MAX_AUTHORIZATION_BYTES = MAX_TOKEN_BYTES + 64

# Documents the scheme in OpenAPI only; its parsed value is never used (parsing is on the raw headers below).
bearer_scheme = HTTPBearer(auto_error=False, description="Access JWT from the CARVIS issuer.")


def database_errors() -> tuple[type[BaseException], ...]:
    """Every exception meaning "the database is unavailable" on the request path (⇒ 503)."""
    import psycopg
    from sqlalchemy import exc as sa_exc

    from db.conninfo import ConnectionConfigError
    from db.readiness import NoAddress, ResolverBusy, RuntimeRoleMissing, UnsafeLogin

    return (NoAddress, ResolverBusy, ConnectionConfigError, RuntimeRoleMissing, UnsafeLogin, OSError, TimeoutError,
            psycopg.Error, sa_exc.DBAPIError, sa_exc.InterfaceError, sa_exc.TimeoutError)


def unavailable(reason: str) -> ApiError:
    return ApiError(SERVICE_UNAVAILABLE, reason)


def bearer_token(scope: dict) -> str:
    """The bearer token from exactly one ``Authorization`` header, or :class:`ApiError` 401."""
    values = [value for name, value in scope.get("headers", []) if name.lower() == AUTHORIZATION]
    if not values:
        raise ApiError(UNAUTHORIZED, "missing_credentials", CHALLENGE)
    if len(values) != 1 or len(values[0]) > MAX_AUTHORIZATION_BYTES:
        raise ApiError(UNAUTHORIZED, "invalid_credentials", INVALID_TOKEN_CHALLENGE)
    try:
        value = values[0].decode("ascii")
    except UnicodeDecodeError:
        raise ApiError(UNAUTHORIZED, "invalid_credentials", INVALID_TOKEN_CHALLENGE) from None
    match = _BEARER.fullmatch(value)
    if match is not None:
        return match.group(1)
    if _BEARER_SCHEME.fullmatch(value) is None:
        raise ApiError(UNAUTHORIZED, "missing_credentials", CHALLENGE)  # another scheme: no bearer credential
    raise ApiError(UNAUTHORIZED, "invalid_credentials", INVALID_TOKEN_CHALLENGE)


class LoginGate:
    """Doc 04: outside local, ``/v1`` stays at 503 until the runtime login passes the B2a login check.

    The check (:func:`db.readiness._check_login`, the readiness self-check) runs on a raw pooled connection of the
    request engine: no session context, only ``pg_catalog`` reads, transaction-scoped timeouts, rolled back. The
    first success is kept for the process; a failure is not. Concurrent callers share one shielded in-flight check.
    """

    def __init__(self, engine, deadline_seconds: float = LOGIN_CHECK_DEADLINE_SECONDS) -> None:
        self._engine = engine
        self._deadline = deadline_seconds
        self._passed = False
        self._inflight: asyncio.Future | None = None
        self.checks = 0

    @property
    def passed(self) -> bool:
        return self._passed

    async def ensure(self) -> None:
        if self._passed:
            return
        if self._inflight is None or self._inflight.done():
            self._inflight = asyncio.ensure_future(self._check())
            self._inflight.add_done_callback(_consume)
        await asyncio.shield(self._inflight)

    async def _check(self) -> None:
        from db.readiness import _check_login

        self.checks += 1
        async with asyncio.timeout(self._deadline):  # covers the pool checkout and connect too
            connection = await self._engine.connect()
            await self._run(connection, _check_login)
        self._passed = True

    @staticmethod
    async def _run(connection, check_login) -> None:
        try:
            await connection.exec_driver_sql(f"SET LOCAL statement_timeout = {GATE_STATEMENT_TIMEOUT_MS}")
            await connection.exec_driver_sql(f"SET LOCAL lock_timeout = {GATE_LOCK_TIMEOUT_MS}")
            raw = await connection.get_raw_connection()
            async with raw.driver_connection.cursor() as cursor:
                await check_login(cursor)
            await connection.rollback()
        except BaseException:
            await connection.invalidate()  # never return a connection in an unknown state to the pool
            raise
        finally:
            await connection.close()


def _consume(future: asyncio.Future) -> None:
    if not future.cancelled():
        future.exception()


@dataclass
class V1Runtime:
    """What ``/v1`` needs at request time; built in the lifespan (``main``) and closed at shutdown."""

    environment: str
    verifier: object | None
    session_factory: object | None
    login_gate: LoginGate | None
    deadline_seconds: float = REQUEST_DATABASE_DEADLINE_SECONDS
    closers: list[Callable] = field(default_factory=list)

    async def close(self) -> None:
        closers, self.closers = self.closers, []
        for closer in reversed(closers):
            result = closer()
            if asyncio.iscoroutine(result):
                await result


def build_v1_runtime(settings) -> V1Runtime:
    """The runtime for ``settings``. Creates clients and the engine but connects to nothing."""
    import httpx

    from auth.tokens import build_verifier
    from db.context import create_request_session_factory
    from webhook_auth import LOCAL

    runtime = V1Runtime(settings.environment, None, None, None)
    if settings.auth.configured:
        client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
        runtime.closers.append(client.aclose)
        runtime.verifier = build_verifier(settings.auth, client, settings.environment)
    if settings.database_ready_to_probe:
        from db.engine import create_async_app_engine

        engine, resolver = create_async_app_engine(settings.database_url)
        runtime.closers.append(resolver.shutdown)
        runtime.closers.append(engine.dispose)
        runtime.session_factory = create_request_session_factory(engine)
        if settings.environment != LOCAL:
            runtime.login_gate = LoginGate(engine)
    return runtime


@dataclass(frozen=True)
class Caller:
    principal: Principal
    user: ProvisionedUser
    runtime: V1Runtime = field(repr=False)


async def current_caller(request: Request, _documented=Security(bearer_scheme)) -> Caller:
    """Steps 1–8 of the module docstring. The tenant unit of work (step 9) is :func:`tenant`."""
    runtime = getattr(request.app.state, "v1", None)
    if not isinstance(runtime, V1Runtime):
        raise unavailable("v1_not_started")
    if runtime.verifier is None:
        raise unavailable("auth_unconfigured")
    if runtime.session_factory is None:
        raise unavailable("database_unconfigured")
    token = bearer_token(request.scope)
    try:
        principal = await runtime.verifier.verify(token)
    except InvalidToken as exc:
        raise ApiError(UNAUTHORIZED, "token_rejected", INVALID_TOKEN_CHALLENGE) from exc
    except AuthUnavailable:
        raise unavailable("auth_unavailable") from None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + runtime.deadline_seconds
    request.state.v1_deadline = deadline
    errors = database_errors()
    from db.readiness import RuntimeRoleMissing, UnsafeLogin

    try:
        async with asyncio.timeout_at(deadline):
            if runtime.login_gate is not None:
                await runtime.login_gate.ensure()
            user = await provision(runtime.session_factory,
                                   BootstrapContext(principal.issuer, principal.subject, principal.email))
    except TimeoutError:
        raise unavailable("request_deadline") from None
    except (UnsafeLogin, RuntimeRoleMissing) as exc:
        raise unavailable("login_unsafe") from exc
    except errors as exc:
        raise unavailable("database_unavailable") from exc
    if user.status != "active":
        raise ApiError(UNAUTHORIZED, "inactive_user", INVALID_TOKEN_CHALLENGE)
    return Caller(principal, user, runtime)


@asynccontextmanager
async def tenant(request: Request, caller: Caller) -> AsyncIterator[AsyncSession]:
    """Step 9: the caller's tenant unit of work, within the request's remaining deadline; failures ⇒ 503."""
    errors = database_errors()
    deadline = getattr(request.state, "v1_deadline", None)
    if deadline is None:
        deadline = asyncio.get_running_loop().time() + caller.runtime.deadline_seconds
    try:
        async with asyncio.timeout_at(deadline):
            async with tenant_session(caller.runtime.session_factory, caller.user) as session:
                yield session
    except TimeoutError:
        raise unavailable("request_deadline") from None
    except errors as exc:
        raise unavailable("database_unavailable") from exc
