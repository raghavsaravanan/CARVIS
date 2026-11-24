"""M2 B2c: the /v1 auth dependency, error envelope, headers and OpenAPI snapshot, without a database.

Tokens are signed by local keys and verified against a fake JWKS (``httpx.MockTransport``); provisioning and the
tenant session are replaced by fakes that record calls. Real-PostgreSQL behavior is in ``test_b2c_v1_postgres.py``.
Labels: mocked/unit.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import exc as sa_exc

import api_v1.auth as v1auth
import api_v1.routes as v1routes
import main
from api_v1.auth import LoginGate, V1Runtime, bearer_token, build_v1_runtime, database_errors
from api_v1.errors import ApiError, ErrorEnvelope, is_v1_path, v1_route_class
from auth.jwks import JwksCache
from auth.tokens import TokenVerifier
from db.context import ProvisionedUser
from request_limits import BodyLimit
from settings import AuthSettings, Settings
from tests.test_b2a_jwt import (AUDIENCE, CLAIM_CASES, EC_KEY, ISSUER, JWKS_URL, OTHER_EC_KEY, RSA_KEY, FakeIssuer,
                                claims, default_keys, sign)

SNAPSHOT = Path(__file__).parent / "fixtures" / "openapi-v1.json"
FIXTURES = Path(__file__).parent / "fixtures" / "v1"
USER = ProvisionedUser(uuid.UUID("0190a000-0000-7000-8000-000000000001"), "active")
INVALID = 'Bearer error="invalid_token"'


class Recorder:
    def __init__(self, status: str = "active", error: BaseException | None = None) -> None:
        self.calls: list = []
        self.status = status
        self.error = error

    async def provision(self, factory, context):
        self.calls.append(context)
        if self.error is not None:
            raise self.error
        return ProvisionedUser(USER.user_id, self.status)


@pytest.fixture
def issuer():
    return FakeIssuer(default_keys())


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(v1auth, "provision", rec.provision)
    return rec


def runtime_for(issuer: FakeIssuer, *, verifier=True, factory=True, gate=None, clock=None) -> V1Runtime:
    client = httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler))
    cache = JwksCache(JWKS_URL, client, **({"clock": clock} if clock else {}))
    return V1Runtime("staging", TokenVerifier(ISSUER, AUDIENCE, cache, clock=time.time) if verifier else None,
                     object() if factory else None, gate)


@pytest.fixture
def client():
    original = getattr(main.app.state, "v1", None)
    yield TestClient(main.app)
    main.app.state.v1 = original


def install(runtime) -> None:
    main.app.state.v1 = runtime


def token(**overrides) -> str:
    return sign(claims(**overrides))


def bearer(value: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {value or token()}"}


def assert_envelope(response, status: int, code: str, retryable: bool | None = None) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "request_id", "retryable"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    if retryable is not None:
        assert body["error"]["retryable"] is retryable
    return body["error"]


# --- Startup and configuration (pipeline steps 1-3) -----------------------------------------------

def test_v1_without_a_runtime_is_503(client, recorder):
    main.app.state.v1 = None
    for path in ("/v1/me", "/v1/workspaces"):
        assert_envelope(client.get(path, headers=bearer()), 503, "service_unavailable", True)
    assert recorder.calls == []


def test_v1_without_issuer_settings_is_503_and_legacy_is_unaffected(client, issuer, recorder):
    install(runtime_for(issuer, verifier=False))
    assert_envelope(client.get("/v1/me", headers=bearer()), 503, "service_unavailable", True)
    assert_envelope(client.get("/v1/me"), 503, "service_unavailable")  # configuration is checked first
    assert client.get("/health").json() == {"status": "ok", "service": "carvis"}
    assert recorder.calls == []


def test_v1_without_database_is_503(client, issuer, recorder):
    install(runtime_for(issuer, factory=False))
    assert_envelope(client.get("/v1/me", headers=bearer()), 503, "service_unavailable", True)
    assert recorder.calls == []


# --- Bearer credential grammar (matrix B1-B10) -----------------------------------------------------

def test_valid_bearer_token_reaches_provisioning(client, issuer, recorder, monkeypatch):
    install(runtime_for(issuer))
    monkeypatch.setattr(v1auth, "tenant_session", failing_tenant(psycopg.OperationalError("down")))
    for scheme in ("Bearer", "bearer", "BEARER", "Bearer  "):
        response = client.get("/v1/me", headers={"Authorization": f"{scheme} {token()}"})
        assert_envelope(response, 503, "service_unavailable")  # passed auth, failed at the tenant step
    assert len(recorder.calls) == 4
    assert recorder.calls[0].subject == "user-123" and recorder.calls[0].issuer == ISSUER


@pytest.mark.parametrize("header", [None, "Basic dXNlcjpwYXNz", "Token abc", "Bearerabc"])
def test_no_bearer_credential_is_401_with_a_plain_challenge(client, issuer, recorder, header):
    install(runtime_for(issuer))
    response = client.get("/v1/me", headers={} if header is None else {"Authorization": header})
    assert_envelope(response, 401, "unauthorized", False)
    assert response.headers["www-authenticate"] == "Bearer"
    assert recorder.calls == []


@pytest.mark.parametrize("value", ["Bearer", "Bearer ", "Bearer\tTOKEN", "Bearer a b", "Bearer abc def",
                                   "Bearer ab\"c", "Bearer abc,", "Bearer =abc"])
def test_malformed_bearer_credentials_are_invalid_token(client, issuer, recorder, value):
    install(runtime_for(issuer))
    response = client.get("/v1/me", headers={"Authorization": value})
    assert_envelope(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == INVALID
    assert recorder.calls == []


def test_trailing_data_after_a_valid_token_is_refused(issuer):
    for raw in (f"Bearer {token()} extra", f"Bearer {token()}\t", f"Bearer {token()}\x00"):
        with pytest.raises(ApiError) as error:
            bearer_token({"headers": [(b"authorization", raw.encode("latin-1"))]})
        assert error.value.reason == "invalid_credentials"


def test_non_ascii_header_bytes_are_refused():
    with pytest.raises(ApiError) as error:
        bearer_token({"headers": [(b"authorization", b"Bearer abc\xff")]})
    assert error.value.reason == "invalid_credentials"


def test_two_authorization_headers_are_refused(client, issuer, recorder):
    install(runtime_for(issuer))
    response = client.get("/v1/me", headers=[("Authorization", f"Bearer {token()}"),
                                              ("Authorization", f"Bearer {token()}")])
    assert_envelope(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == INVALID
    assert recorder.calls == []


def test_oversized_authorization_header_is_refused_before_decoding(client, issuer, recorder):
    install(runtime_for(issuer))
    response = client.get("/v1/me", headers={"Authorization": "Bearer " + "a" * 9000})
    assert_envelope(response, 401, "unauthorized")
    assert issuer.requests == 0 and recorder.calls == []


def test_token_in_query_or_body_is_ignored(client, issuer, recorder):
    install(runtime_for(issuer))
    response = client.get("/v1/me", params={"access_token": token()})
    assert_envelope(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == "Bearer"
    assert recorder.calls == []


# --- ADR-0002 token matrix through the routes (F1) -------------------------------------------------

def _hmac_token() -> str:
    import hashlib
    import hmac

    from cryptography.hazmat.primitives import serialization

    pem = RSA_KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "kid": "rsa-1"}).encode()).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(claims()).encode()).rstrip(b"=")
    mac = base64.urlsafe_b64encode(hmac.new(pem, header + b"." + body, hashlib.sha256).digest()).rstrip(b"=")
    return (header + b"." + body + b"." + mac).decode()


def _alg_none_token() -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "ec-1"}).encode()).rstrip(b"=").decode()
    return f"{header}.{sign(claims()).split('.')[1]}.c2ln"


ROUTE_TOKEN_CASES = [
    *[(name, lambda build=build: sign(build(int(time.time())))) for name, build, _ in CLAIM_CASES],
    ("bad-signature", lambda: sign(claims(), OTHER_EC_KEY)),
    ("unknown-kid", lambda: sign(claims(), kid="not-published")),
    ("alg-none", _alg_none_token),
    ("hmac-with-public-key", _hmac_token),
    ("missing-kid", lambda: sign(claims(), kid=None)),
    ("header-jku", lambda: sign(claims(), headers={"jku": "https://evil.test/jwks"})),
    ("header-x5u", lambda: sign(claims(), headers={"x5u": "https://evil.test/c"})),
    ("header-jwk", lambda: sign(claims(), headers={"jwk": {"kty": "EC"}})),
    ("header-x5c", lambda: sign(claims(), headers={"x5c": ["MIIB"]})),
    ("header-crit", lambda: sign(claims(), headers={"crit": ["exp"]})),
]


@pytest.mark.parametrize("build", [case[1] for case in ROUTE_TOKEN_CASES], ids=[case[0] for case in ROUTE_TOKEN_CASES])
def test_every_adr_0002_refusal_is_401_through_v1_me(client, issuer, recorder, build):
    install(runtime_for(issuer))
    response = client.get("/v1/me", headers={"Authorization": f"Bearer {build()}"})
    error = assert_envelope(response, 401, "unauthorized", False)
    assert response.headers["www-authenticate"] == INVALID
    assert error["message"] == "Authentication is required."
    assert recorder.calls == []  # no database statement: provisioning is never reached


def test_a_refused_token_through_v1_workspaces(client, issuer, recorder):
    install(runtime_for(issuer))
    response = client.get("/v1/workspaces", headers=bearer(token(role="anon")))
    assert_envelope(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == INVALID
    assert recorder.calls == []


@pytest.mark.parametrize("status", ["deleting", "deleted"])
def test_non_active_user_is_401_without_a_tenant_transaction(client, issuer, recorder, monkeypatch, status):
    install(runtime_for(issuer))
    recorder.status = status
    opened = []
    monkeypatch.setattr(v1auth, "tenant_session", lambda *a: opened.append(a))
    for path in ("/v1/me", "/v1/workspaces"):
        response = client.get(path, headers=bearer())
        assert_envelope(response, 401, "unauthorized")
        assert response.headers["www-authenticate"] == INVALID
    assert opened == [] and len(recorder.calls) == 2


# --- Issuer availability (matrix J2, D06) ----------------------------------------------------------

class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_no_usable_keys_is_503_never_401(client, issuer, recorder):
    issuer.status = 500
    install(runtime_for(issuer))
    response = client.get("/v1/me", headers=bearer())
    assert_envelope(response, 503, "service_unavailable", True)
    assert "www-authenticate" not in response.headers and recorder.calls == []


def test_cached_keys_during_an_outage(client, issuer, recorder, monkeypatch):
    """(b) a cached kid still verifies while refreshes fail; (c) an unknown kid is 401; past 1 h stale, 503."""
    clock = Clock()
    install(runtime_for(issuer, clock=clock))
    monkeypatch.setattr(v1auth, "tenant_session", failing_tenant(psycopg.OperationalError("down")))
    assert_envelope(client.get("/v1/me", headers=bearer()), 503, "service_unavailable")  # keys fetched once
    issuer.status = 500
    clock.now += 700  # cache expired, refresh fails, last good keys still usable
    assert len(recorder.calls) == 1
    client.get("/v1/me", headers=bearer())
    assert len(recorder.calls) == 2  # (b) authenticated with the cached key
    response = client.get("/v1/me", headers=bearer(sign(claims(), kid="rotated-away")))
    assert_envelope(response, 401, "unauthorized")  # (c)
    clock.now += 3600  # beyond the stale window: no usable keys
    assert_envelope(client.get("/v1/me", headers=bearer()), 503, "service_unavailable", True)


# --- Database availability, deadline and the login gate (D01, D02, P1-P4) --------------------------

def failing_tenant(error: BaseException):
    @asynccontextmanager
    async def fake(factory, user):
        raise error
        yield  # pragma: no cover

    return fake


def _database_error_cases():
    from db.conninfo import ConnectionConfigError
    from db.readiness import NoAddress, ResolverBusy, RuntimeRoleMissing, UnsafeLogin

    return [NoAddress(), ResolverBusy(), ConnectionConfigError("x"), RuntimeRoleMissing(), UnsafeLogin("superuser"),
            OSError("x"), TimeoutError(), psycopg.OperationalError("x"),
            sa_exc.OperationalError("SELECT 1", {}, Exception("x")), sa_exc.InterfaceError("SELECT 1", {}, Exception()),
            sa_exc.TimeoutError("pool")]


@pytest.mark.parametrize("error", _database_error_cases(), ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("step", ["gate", "provision", "tenant"])
def test_every_database_error_at_every_step_is_503(client, issuer, monkeypatch, step, error):
    gate = None
    if step == "gate":
        gate = LoginGate(engine=None)

        async def check():
            raise error

        gate._check = check
    rec = Recorder(error=error if step == "provision" else None)
    monkeypatch.setattr(v1auth, "provision", rec.provision)
    monkeypatch.setattr(v1auth, "tenant_session", failing_tenant(error))
    install(runtime_for(issuer, gate=gate))
    error_body = assert_envelope(client.get("/v1/me", headers=bearer()), 503, "service_unavailable", True)
    assert type(error).__name__ not in json.dumps(error_body) and "x" != error_body["message"]


def test_database_error_class_is_complete():
    from db.readiness import NoAddress

    assert NoAddress in database_errors()
    for error in _database_error_cases():
        assert isinstance(error, database_errors())


def test_request_deadline_is_503(client, issuer, monkeypatch):
    async def slow(factory, context):
        await asyncio.sleep(5)

    monkeypatch.setattr(v1auth, "provision", slow)
    runtime = runtime_for(issuer)
    runtime.deadline_seconds = 0.2
    install(runtime)
    started = time.monotonic()
    assert_envelope(client.get("/v1/me", headers=bearer()), 503, "service_unavailable", True)
    assert time.monotonic() - started < 2


def test_tenant_step_shares_the_request_deadline(client, issuer, recorder, monkeypatch):
    @asynccontextmanager
    async def slow_tenant(factory, user):
        await asyncio.sleep(5)
        yield None  # pragma: no cover

    monkeypatch.setattr(v1auth, "tenant_session", slow_tenant)
    runtime = runtime_for(issuer)
    runtime.deadline_seconds = 0.2
    install(runtime)
    started = time.monotonic()
    assert_envelope(client.get("/v1/workspaces", headers=bearer()), 503, "service_unavailable")
    assert time.monotonic() - started < 2


def test_login_gate_is_single_flight_and_caches_success_only():
    async def scenario():
        gate = LoginGate(engine=None)
        results = iter([RuntimeError("unsafe"), None])
        started = asyncio.Event()
        release = asyncio.Event()

        async def check():
            gate.checks += 1
            started.set()
            await release.wait()
            outcome = next(results)
            if outcome is not None:
                raise outcome
            gate._passed = True

        gate._check = check
        waiters = [asyncio.ensure_future(gate.ensure()) for _ in range(5)]
        await started.wait()
        release.set()
        outcomes = await asyncio.gather(*waiters, return_exceptions=True)
        assert gate.checks == 1 and all(isinstance(o, RuntimeError) for o in outcomes)
        assert not gate.passed  # a failure is not cached
        await gate.ensure()
        await gate.ensure()
        assert gate.checks == 2 and gate.passed  # success is cached

    asyncio.run(scenario())


def test_login_gate_survives_a_cancelled_first_caller():
    async def scenario():
        gate = LoginGate(engine=None)
        release = asyncio.Event()

        async def check():
            gate.checks += 1
            await release.wait()
            gate._passed = True

        gate._check = check
        first = asyncio.ensure_future(gate.ensure())
        second = asyncio.ensure_future(gate.ensure())
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)
        release.set()
        await second
        assert gate.passed and gate.checks == 1

    asyncio.run(scenario())


def test_unsafe_login_gate_failure_is_503(client, issuer, recorder):
    from db.readiness import UnsafeLogin

    gate = LoginGate(engine=None)

    async def check():
        raise UnsafeLogin("superuser")

    gate._check = check
    install(runtime_for(issuer, gate=gate))
    assert_envelope(client.get("/v1/me", headers=bearer()), 503, "service_unavailable", True)
    assert recorder.calls == []


# --- Runtime construction (L1, L2) ------------------------------------------------------------------

def _settings(environment: str, *, auth: bool, database: bool) -> Settings:
    from settings import normalize_database_url

    status, url = normalize_database_url("postgresql://u:p@127.0.0.1:1/db" if database else None)
    auth_settings = AuthSettings("configured", ISSUER, AUDIENCE, JWKS_URL) if auth else AuthSettings("unconfigured")
    return Settings(environment=environment, database_status=status, database_url=url, auth=auth_settings)


@pytest.mark.parametrize("environment,gated", [("local", False), ("staging", True), ("production", True)])
def test_build_runtime_from_settings(environment, gated):
    runtime = build_v1_runtime(_settings(environment, auth=True, database=True))
    try:
        assert runtime.verifier is not None and runtime.session_factory is not None
        assert (runtime.login_gate is not None) is gated
        client = runtime.verifier._jwks._client
        assert client.trust_env is False and client.follow_redirects is False
    finally:
        asyncio.run(runtime.close())
    assert runtime.closers == []


def test_build_runtime_without_settings_connects_nothing():
    runtime = build_v1_runtime(_settings("staging", auth=False, database=False))
    assert runtime.verifier is None and runtime.session_factory is None and runtime.login_gate is None
    asyncio.run(runtime.close())


# --- Envelope scope and headers (E1-E8, D04, F8, F9) ------------------------------------------------

def test_unknown_v1_path_and_wrong_method_use_the_envelope(client, issuer):
    install(runtime_for(issuer))
    assert_envelope(client.get("/v1/nope"), 404, "not_found")
    assert_envelope(client.get("/v1"), 404, "not_found")
    response = client.post("/v1/me")
    assert_envelope(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "GET"


def test_legacy_error_shapes_are_unchanged(client):
    assert client.get("/nope").content == b'{"detail":"Not Found"}'
    assert client.get("/v1x").content == b'{"detail":"Not Found"}'
    response = client.post("/healthz")
    assert response.status_code == 405 and response.json() == {"detail": "Method Not Allowed"}
    assert "cache-control" not in client.get("/healthz").headers
    response = client.put("/conversation/sessions/x/vehicle", json={"year": "not-a-year"},
                          headers={"Authorization": "Bearer x"})
    assert "error" not in response.json()


def test_redirect_on_v1_carries_no_store(client):
    response = client.get("/v1/me/", follow_redirects=False)
    assert response.status_code == 307 and response.headers["cache-control"] == "no-store"


def test_validation_failure_uses_the_envelope_and_never_echoes_input(client, issuer, recorder, monkeypatch):
    install(runtime_for(issuer))
    for params in ({"limit": "0"}, {"limit": "101"}, {"limit": "abc"}, {"cursor": "SECRETVALUE"},
                   {"cursor": "A" * 21 + "B"}, {"cursor": "x" * 65}):
        response = client.get("/v1/workspaces", params=params, headers=bearer())
        assert_envelope(response, 422, "validation_failed", False)
        assert "SECRETVALUE" not in response.text and "abc" not in response.text


def test_unexpected_error_is_a_generic_500_with_the_request_id(client, issuer, recorder, monkeypatch, caplog):
    install(runtime_for(issuer))

    @asynccontextmanager
    async def broken(factory, user):
        raise ValueError("secret detail user-123")
        yield  # pragma: no cover

    monkeypatch.setattr(v1auth, "tenant_session", broken)
    request_id = uuid.uuid4().hex
    with caplog.at_level(logging.ERROR, logger="carvis.v1"):
        response = client.get("/v1/me", headers={**bearer(), "X-Request-ID": request_id})
    error = assert_envelope(response, 500, "server_error", False)
    assert error["request_id"] == request_id
    fields = [getattr(record, "carvis_fields", {}) for record in caplog.records]
    assert "secret detail" not in response.text and "secret detail" not in caplog.text + json.dumps(fields)
    assert {"code": "server_error", "reason": "unhandled_error", "error": "ValueError"} in fields


class Body(BaseModel):
    value: str


def test_body_limit_rejections_on_a_v1_route_use_the_envelope():
    app = FastAPI()
    main_install = __import__("api_v1.errors", fromlist=["install"]).install
    main_install(app)
    from fastapi import APIRouter

    router = APIRouter(prefix="/v1", route_class=v1_route_class({}, BodyLimit(16)))

    @router.post("/echo")
    async def echo(body: Body) -> dict:
        return {"ok": True}

    app.include_router(router)
    client = TestClient(app)
    response = client.post("/v1/echo", content=b'{"value": "' + b"x" * 64 + b'"}',
                           headers={"content-type": "application/json"})
    assert response.status_code == 413 and response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["connection"] == "close"
    response = client.post("/v1/echo", content=b"{}", headers={"content-type": "application/json"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_failed"


def flat_routes(routes):
    """Routes, with FastAPI's included routers expanded (test-only use of its private wrapper)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from flat_routes(inner.routes)
        else:
            yield route


def test_the_v1_router_itself_requires_the_caller():
    """F8: authentication is router-level, so a future /v1 route cannot omit it."""
    assert [d.dependency for d in v1routes.router.dependencies] == [v1auth.current_caller]


def test_every_v1_route_requires_the_caller(client, issuer):
    """F8: every route under /v1, present or future, answers 401 with the envelope without credentials."""
    install(runtime_for(issuer))
    routes = [r for r in flat_routes(main.app.routes) if is_v1_path(getattr(r, "path", ""))]
    assert {r.path for r in routes} >= {"/v1/me", "/v1/workspaces"}
    assert {r.path for r in routes} >= {p for p in main.app.openapi()["paths"] if is_v1_path(p)}
    for route in routes:
        for method in route.methods - {"HEAD"}:
            response = client.request(method, route.path.replace("{", "").replace("}", ""))
            assert_envelope(response, 401, "unauthorized")


# --- Formats, fixtures and OpenAPI (F4, F7, F12, D07, O1, O2) ---------------------------------------

def test_timestamps_are_utc_whole_seconds_whatever_the_offset():
    from datetime import datetime, timedelta, timezone

    value = datetime(2026, 11, 24, 10, 0, 0, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert v1routes.utc_timestamp(value) == "2026-11-24T04:30:00Z"
    with pytest.raises(ValueError):
        v1routes.utc_timestamp(datetime(2026, 1, 1))


def test_cursor_round_trip_and_refusals():
    workspace = uuid.uuid4()
    assert v1routes.decode_cursor(v1routes.encode_cursor(workspace)) == workspace
    for bad in ("", "abc", workspace.hex, str(workspace), "A" * 21 + "=", "!" * 22,
                v1routes.encode_cursor(workspace)[:-1] + "B"):
        if bad == v1routes.encode_cursor(workspace):
            continue
        with pytest.raises(ApiError):
            v1routes.decode_cursor(bad)


def test_fixtures_match_the_response_models():
    import re

    stamp = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
    me = v1routes.Me.model_validate_json((FIXTURES / "me.json").read_text())
    page = v1routes.WorkspacePage.model_validate_json((FIXTURES / "workspaces.json").read_text())
    ErrorEnvelope.model_validate_json((FIXTURES / "error.json").read_text())
    assert stamp.fullmatch(me.created_at)
    assert page.items and all(stamp.fullmatch(item.created_at) for item in page.items)
    if page.next_cursor is not None:
        v1routes.decode_cursor(page.next_cursor)


def v1_openapi() -> dict:
    """``app.openapi()`` restricted to /v1 paths and the components they reference."""
    full = main.app.openapi()
    paths = {path: item for path, item in full["paths"].items() if is_v1_path(path)}
    schemas = full.get("components", {}).get("schemas", {})
    needed: set[str] = set()
    pending = [paths]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[1]
                if name not in needed:
                    needed.add(name)
                    pending.append(schemas[name])
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    components = {"schemas": {name: schemas[name] for name in sorted(needed)},
                  "securitySchemes": full["components"]["securitySchemes"]}
    return {"openapi": full["openapi"], "paths": paths, "components": components}


def test_openapi_v1_snapshot():
    current = json.dumps(v1_openapi(), indent=2, sort_keys=True) + "\n"
    if os.getenv("CARVIS_UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.write_text(current)
    assert SNAPSHOT.read_text() == current, (
        "The /v1 OpenAPI contract changed. If the change is intended and additive (ADR-0004), regenerate with "
        "CARVIS_UPDATE_OPENAPI_SNAPSHOT=1 .venv/bin/python -m pytest backend/tests/test_b2c_v1_api.py -k snapshot")


def test_openapi_v1_declares_bearer_security_and_the_envelope():
    spec = v1_openapi()
    assert spec["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http", "scheme": "bearer", "description": "Access JWT from the CARVIS issuer."}
    assert "HTTPValidationError" not in json.dumps(spec)
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            assert operation["security"] == [{"HTTPBearer": []}], (path, method)
            for status in ("401", "500", "503"):
                ref = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorEnvelope"), (path, status)
            if operation.get("parameters"):
                assert operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
                    "/ErrorEnvelope")


def test_login_gate_deadline_covers_the_pool_checkout():
    """Pre-review: a stalled checkout or connect is bounded by the gate's own deadline, not only the caller's."""
    class StalledEngine:
        async def connect(self):
            await asyncio.sleep(30)

    async def scenario():
        gate = LoginGate(StalledEngine(), deadline_seconds=0.2)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await gate.ensure()
        assert time.monotonic() - started < 2 and not gate.passed

    asyncio.run(scenario())


# --- Unread announced bodies (implementation review round 1: Claude F1 / Codex B1) --------------------
#
# Rule (A6): any response sent without reading an announced body carries Connection: close, so the server does not
# drain the rest on keep-alive. Class: every way a /v1 response is produced. One parametrized case per path.

def _no_runtime(monkeypatch, issuer):
    main.app.state.v1 = None


def _runtime(monkeypatch, issuer):
    install(runtime_for(issuer))


def _database_down(monkeypatch, issuer):
    install(runtime_for(issuer))
    monkeypatch.setattr(v1auth, "provision", Recorder(error=psycopg.OperationalError("down")).provision)


def _unexpected(monkeypatch, issuer):
    install(runtime_for(issuer))
    monkeypatch.setattr(v1auth, "provision", Recorder().provision)
    monkeypatch.setattr(v1auth, "tenant_session", failing_tenant(ValueError("boom")))


def _authenticated(monkeypatch, issuer):
    install(runtime_for(issuer))
    monkeypatch.setattr(v1auth, "provision", Recorder().provision)


UNREAD_BODY_CASES = [
    ("401-no-credentials", _runtime, "GET", "/v1/me", {}, 401),
    ("401-invalid-token", _runtime, "GET", "/v1/me", {"Authorization": "Bearer a.b.c"}, 401),
    ("401-workspaces", _runtime, "GET", "/v1/workspaces", {}, 401),
    ("503-no-runtime", _no_runtime, "GET", "/v1/me", {}, 503),
    ("503-database", _database_down, "GET", "/v1/me", None, 503),
    ("500-unexpected", _unexpected, "GET", "/v1/me", None, 500),
    ("422-validation", _authenticated, "GET", "/v1/workspaces?limit=0", None, 422),
    ("404-unknown-path", _runtime, "GET", "/v1/nope", {}, 404),
    ("405-wrong-method", _runtime, "DELETE", "/v1/me", {}, 405),
    ("307-redirect", _runtime, "GET", "/v1/me/", {}, 307),
]


@pytest.mark.parametrize("prepare,method,path,headers,status", [case[1:] for case in UNREAD_BODY_CASES],
                         ids=[case[0] for case in UNREAD_BODY_CASES])
def test_every_v1_response_to_an_unread_announced_body_closes_the_connection(client, issuer, monkeypatch, prepare,
                                                                              method, path, headers, status):
    prepare(monkeypatch, issuer)
    headers = bearer() if headers is None else headers
    response = client.request(method, path, content=b"x" * 100_000, headers=headers, follow_redirects=False)
    assert response.status_code == status, response.text
    assert response.headers["connection"] == "close"
    assert response.headers["cache-control"] == "no-store"


def test_v1_response_without_a_body_keeps_the_connection(client, issuer):
    install(runtime_for(issuer))
    response = client.get("/v1/me")
    assert response.status_code == 401 and "connection" not in response.headers


def test_chunked_and_fully_read_bodies():
    """The rule on raw ASGI: chunked counts as announced; a body read to the end before answering does not close."""
    from api_v1.errors import V1HeadersMiddleware

    async def reads_body(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def ignores_body(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": [(b"connection", b"keep-alive")]})
        await send({"type": "http.response.body", "body": b""})

    async def call(app, headers):
        sent = []
        chunks = iter([{"type": "http.request", "body": b"a", "more_body": True},
                       {"type": "http.request", "body": b"b", "more_body": False}])

        async def receive():
            return next(chunks)

        async def send(message):
            sent.append(message)

        await V1HeadersMiddleware(app)({"type": "http", "path": "/v1/me", "headers": headers}, receive, send)
        return dict(sent[0]["headers"])

    chunked = [(b"transfer-encoding", b"chunked")]
    assert b"connection" not in asyncio.run(call(reads_body, chunked))
    assert asyncio.run(call(ignores_body, chunked))[b"connection"] == b"close"
    assert asyncio.run(call(ignores_body, [(b"content-length", b"abc")]))[b"connection"] == b"close"
    assert b"connection" not in asyncio.run(call(reads_body, [(b"content-length", b"2")]))
