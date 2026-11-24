"""M2 B2c: /v1 end to end on real PostgreSQL 16 (labels: local; CI's service container).

The app's real ``/v1`` routes run through ``httpx.ASGITransport`` on one event loop, with the B2a request engine on a
provisioned runtime login (INHERIT FALSE member of ``carvis_app`` and ``carvis_bootstrap``), the B2b-1 schema
migrated by a non-superuser CREATEROLE login, the B2b-2 session context, and a JWT verifier over a fake JWKS.
Covers the design matrix rows J4-J6, P1-P3, D1-D3, R1-R5, G1-G2 and the D02 lock-contention deadline.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid

import httpx
import psycopg
import pytest

import main
from api_v1.auth import LoginGate, V1Runtime
from auth.jwks import JwksCache
from auth.tokens import TokenVerifier
from db.context import SET_APP_ROLE, create_request_session_factory
from tests.test_b1_migrations import _sql, _url, admin_url, scratch  # noqa: F401
from tests.test_b2a_jwt import AUDIENCE, ISSUER, JWKS_URL, FakeIssuer, claims, default_keys, sign
from tests.test_b2a_migrations import migrator  # noqa: F401
from tests.test_b2b1_identity import head, login  # noqa: F401
from tests.test_b2b2_context import captured, clean, raw_state

RUNTIME = "b1_runtime"
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def run(url: str, scenario, *, environment: str = "local", deadline: float = 5.0, pool_size: int = 2,
        keys=None):
    """Run ``scenario(client, runtime, engine)`` against the real app with a runtime for ``url``."""
    from db.engine import create_async_app_engine
    from settings import normalize_database_url

    _, database_url = normalize_database_url(url)
    issuer = FakeIssuer(keys or default_keys())

    async def main_():
        engine, resolver = create_async_app_engine(database_url, pool_size=pool_size, max_overflow=0)
        jwks = httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler))
        runtime = V1Runtime(environment, TokenVerifier(ISSUER, AUDIENCE, JwksCache(JWKS_URL, jwks), clock=time.time),
                            create_request_session_factory(engine),
                            LoginGate(engine) if environment != "local" else None, deadline_seconds=deadline)
        original = getattr(main.app.state, "v1", None)
        main.app.state.v1 = runtime
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://carvis") as c:
                return await scenario(c, runtime, engine)
        finally:
            main.app.state.v1 = original
            await jwks.aclose()
            await engine.dispose()
            resolver.shutdown()

    return asyncio.run(main_())


def auth(subject: str, **overrides) -> dict[str, str]:
    return {"Authorization": "Bearer " + sign(claims(sub=subject, **overrides))}


def user_id_of(scratch, subject: str) -> str:
    rows = _sql(scratch.db_admin, f"SELECT id::text FROM carvis.users WHERE auth_subject = '{subject}'", fetch=True)
    return rows[0][0]


def add_shop(scratch, user_id: str, name: str, role: str = "member") -> str:
    workspace = _sql(scratch.db_admin, f"INSERT INTO carvis.workspaces (kind, name) VALUES ('shop', '{name}') "
                                       "RETURNING id::text", fetch=True)[0][0]
    _sql(scratch.db_admin, f"INSERT INTO carvis.memberships (workspace_id, user_id, role) "
                           f"VALUES ('{workspace}', '{user_id}', '{role}')")
    return workspace


# --- Provisioning and the two routes (J4, J6, F4) --------------------------------------------------

def test_first_request_provisions_and_both_routes_answer(scratch, login):
    async def scenario(client, runtime, engine):
        me = await client.get("/v1/me", headers=auth("tech-a"))
        again = await client.get("/v1/me", headers=auth("tech-a"))
        workspaces = await client.get("/v1/workspaces", headers=auth("tech-a"))
        no_email = await client.get("/v1/me", headers=auth("tech-b", email=...))
        return me, again, workspaces, no_email

    me, again, workspaces, no_email = run(login, scenario)
    assert me.status_code == 200 and me.headers["cache-control"] == "no-store"
    body = me.json()
    assert set(body) == {"id", "email", "display_name", "created_at"}
    assert body["email"] == "tech@example.test" and body["display_name"] is None
    assert STAMP.fullmatch(body["created_at"])
    assert again.json() == body and body["id"] == user_id_of(scratch, "tech-a")
    page = workspaces.json()
    assert page["next_cursor"] is None and len(page["items"]) == 1
    item = page["items"][0]
    assert (item["kind"], item["role"], item["name"]) == ("personal", "owner", "Personal")
    assert STAMP.fullmatch(item["created_at"])
    assert no_email.status_code == 200 and no_email.json()["email"] is None
    counts = _sql(scratch.db_admin, "SELECT (SELECT count(*) FROM carvis.users), (SELECT count(*) FROM "
                                    "carvis.workspaces), (SELECT count(*) FROM carvis.memberships)", fetch=True)
    assert counts == [(2, 2, 2)]


def test_timestamps_are_utc_whatever_the_session_time_zone(scratch, login):
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} SET timezone = 'Asia/Kolkata'")

    async def scenario(client, runtime, engine):
        return (await client.get("/v1/me", headers=auth("tech-tz"))).json()["created_at"]

    stamp = run(login, scenario)
    expected = _sql(scratch.db_admin, "SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') "
                                      "FROM carvis.users", fetch=True)[0][0]
    assert stamp == expected


# --- Isolation and caller-supplied identifiers (R1, R3, R5) -----------------------------------------

def test_users_see_only_their_own_rows_and_caller_ids_are_ignored(scratch, login):
    async def setup(client, runtime, engine):
        for subject in ("tech-a", "tech-b"):
            assert (await client.get("/v1/me", headers=auth(subject))).status_code == 200

    run(login, setup)
    a, b = user_id_of(scratch, "tech-a"), user_id_of(scratch, "tech-b")
    shop_a = add_shop(scratch, a, "Shop A")
    personal_a = _sql(scratch.db_admin, f"SELECT id::text FROM carvis.workspaces WHERE personal_owner_user_id = '{a}'",
                      fetch=True)[0][0]

    async def scenario(client, runtime, engine):
        hostile = {**auth("tech-b"), "X-Workspace-Id": shop_a}
        params = {"user_id": a, "workspace_id": personal_a, "shop_id": shop_a}
        requests = []
        for index in range(20):  # interleaved A/B on a pool of 2
            subject = "tech-a" if index % 2 == 0 else "tech-b"
            headers = auth(subject) if subject == "tech-a" else hostile
            requests.append(client.get("/v1/workspaces", headers=headers, params=params))
            requests.append(client.get("/v1/me", headers=headers, params=params))
        responses = await asyncio.gather(*requests)
        malformed = await client.get("/v1/me", headers={**auth("tech-b"), "X-Workspace-Id": "not-a-uuid"})
        state = await raw_state(engine)
        return responses, malformed, state

    responses, malformed, state = run(login, scenario)
    for index, response in enumerate(responses):
        assert response.status_code == 200, response.text
        owner = "tech-a" if (index // 2) % 2 == 0 else "tech-b"
        body = response.json()
        if "items" in body:
            ids = {item["id"] for item in body["items"]}
            assert ids == ({personal_a, shop_a} if owner == "tech-a" else ids - {personal_a, shop_a})
            assert len(ids) == (2 if owner == "tech-a" else 1)
        else:
            assert body["id"] == (a if owner == "tech-a" else b)
    assert malformed.status_code == 200 and malformed.json()["id"] == b
    assert clean(state, RUNTIME)


# --- Non-active users (J5) --------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["deleting", "deleted"])
def test_non_active_user_is_401_with_no_tenant_transaction(scratch, login, status):
    async def setup(client, runtime, engine):
        assert (await client.get("/v1/me", headers=auth("tech-gone"))).status_code == 200

    run(login, setup)
    _sql(scratch.db_admin, f"UPDATE carvis.users SET status = '{status}' WHERE auth_subject = 'tech-gone'")

    async def scenario(client, runtime, engine):
        with captured() as statements:
            responses = [await client.get(path, headers=auth("tech-gone")) for path in ("/v1/me", "/v1/workspaces")]
        return responses, statements

    responses, statements = run(login, scenario)
    for response in responses:
        assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert SET_APP_ROLE not in statements


# --- Pagination and revocation (G1, G2, R4) ---------------------------------------------------------

def test_pagination_and_revocation(scratch, login):
    async def setup(client, runtime, engine):
        assert (await client.get("/v1/me", headers=auth("tech-a"))).status_code == 200
        assert (await client.get("/v1/me", headers=auth("tech-b"))).status_code == 200

    run(login, setup)
    a, b = user_id_of(scratch, "tech-a"), user_id_of(scratch, "tech-b")
    shops = [add_shop(scratch, a, f"Shop {n}") for n in range(3)]
    other = add_shop(scratch, b, "B only")

    async def scenario(client, runtime, engine):
        first = (await client.get("/v1/workspaces", params={"limit": 2}, headers=auth("tech-a"))).json()
        second = (await client.get("/v1/workspaces", params={"limit": 2, "cursor": first["next_cursor"]},
                                   headers=auth("tech-a"))).json()
        default = (await client.get("/v1/workspaces", headers=auth("tech-a"))).json()
        b_with_a_cursor = (await client.get("/v1/workspaces", params={"cursor": first["next_cursor"]},
                                            headers=auth("tech-b"))).json()
        bad = await client.get("/v1/workspaces", params={"cursor": shops[0]}, headers=auth("tech-a"))
        return first, second, default, b_with_a_cursor, bad

    first, second, default, b_with_a_cursor, bad = run(login, scenario)
    assert len(first["items"]) == 2 and first["next_cursor"] is not None
    assert len(second["items"]) == 2 and second["next_cursor"] is None
    listed = [item["id"] for item in first["items"] + second["items"]]
    assert listed == sorted(listed) and set(listed) == set(shops) | {item["id"] for item in default["items"]}
    assert len(default["items"]) == 4 and default["next_cursor"] is None
    personal_b = _sql(scratch.db_admin, f"SELECT id::text FROM carvis.workspaces WHERE personal_owner_user_id = '{b}'",
                      fetch=True)[0][0]
    assert other not in listed
    # A's cursor only bounds B's own rows: B never sees A's workspaces through it.
    assert {item["id"] for item in b_with_a_cursor["items"]} <= {other, personal_b}
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_failed"

    _sql(scratch.db_admin, f"DELETE FROM carvis.memberships WHERE workspace_id = '{shops[1]}'")

    async def after(client, runtime, engine):
        return (await client.get("/v1/workspaces", headers=auth("tech-a"))).json()

    assert shops[1] not in {item["id"] for item in run(login, after)["items"]}


# --- Runtime-login gate outside local (P1, P2, C11) --------------------------------------------------

def test_gate_passes_the_runtime_login_and_reads_only_the_catalog(scratch, login):
    async def scenario(client, runtime, engine):
        with captured() as statements:
            response = await client.get("/v1/me", headers=auth("tech-gate"))
        second = await client.get("/v1/me", headers=auth("tech-gate"))
        return response, second, statements, runtime.login_gate.checks

    response, second, statements, checks = run(login, scenario, environment="staging")
    assert response.status_code == 200 and second.status_code == 200 and checks == 1
    gate = statements[:statements.index("SELECT session_user") + 2]
    assert "SET LOCAL statement_timeout = 1500" in gate and "SET LOCAL lock_timeout = 500" in gate
    assert not any("carvis." in s or "SET LOCAL ROLE" in s or "set_config" in s for s in gate)


def test_gate_refuses_an_unsafe_login_outside_local(scratch, login):
    superuser = _url(scratch.admin, database=scratch.database)

    async def scenario(client, runtime, engine):
        responses = [await client.get("/v1/me", headers=auth("tech-root")) for _ in range(2)]
        return responses, runtime.login_gate.checks

    responses, checks = run(superuser, scenario, environment="staging")
    for response in responses:
        assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"
    assert checks == 2  # failure is not cached
    assert _sql(scratch.db_admin, "SELECT count(*) FROM carvis.users", fetch=True) == [(0,)]


def test_gate_refuses_when_runtime_roles_are_missing(scratch):
    superuser = _url(scratch.admin, database=scratch.database)

    async def scenario(client, runtime, engine):
        return await client.get("/v1/me", headers=auth("tech-early"))

    assert run(superuser, scenario, environment="production").status_code == 503


# --- Database unavailable (D1, D3) -------------------------------------------------------------------

def test_unmigrated_database_is_503(scratch):
    superuser = _url(scratch.admin, database=scratch.database)  # local: no gate; ensure_principal is missing

    async def scenario(client, runtime, engine):
        return await client.get("/v1/me", headers=auth("tech-early"))

    response = run(superuser, scenario)
    assert response.status_code == 503 and response.json()["error"]["retryable"] is True


@pytest.mark.parametrize("target", ["closed-port", "unresolvable-host"])
def test_unreachable_database_is_503(target):
    url = ("postgresql://u:p@127.0.0.1:1/carvis" if target == "closed-port"
           else "postgresql://u:p@carvis-b2c-no-such-host.invalid:5432/carvis")

    async def scenario(client, runtime, engine):
        return await client.get("/v1/me", headers=auth("tech-x"))

    response = run(url, scenario)
    assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"


# --- Request deadline under lock contention (D02) ----------------------------------------------------

def test_lock_contention_is_a_bounded_503_and_leaves_nothing_behind(scratch, login):
    async def setup(client, runtime, engine):
        assert (await client.get("/v1/me", headers=auth("tech-lock"))).status_code == 200

    run(login, setup)
    locked, release = threading.Event(), threading.Event()

    def hold_lock():
        with psycopg.connect(scratch.db_admin) as conn:
            conn.execute("LOCK TABLE carvis.memberships IN ACCESS EXCLUSIVE MODE")
            locked.set()
            release.wait(30)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    assert locked.wait(10)

    async def scenario(client, runtime, engine):
        started = time.monotonic()
        blocked = await asyncio.wait_for(client.get("/v1/workspaces", headers=auth("tech-lock")), 10)
        elapsed = time.monotonic() - started
        release.set()
        await asyncio.to_thread(holder.join, 10)
        await asyncio.sleep(0.2)
        after = await client.get("/v1/workspaces", headers=auth("tech-lock"))
        state = await raw_state(engine)
        return blocked, elapsed, after, state

    try:
        blocked, elapsed, after, state = run(login, scenario, deadline=1.0)
    finally:
        release.set()
    assert blocked.status_code == 503 and blocked.json()["error"]["code"] == "service_unavailable"
    assert elapsed < 3.0
    assert after.status_code == 200 and clean(state, RUNTIME)
    waiting = _sql(scratch.db_admin, f"SELECT count(*) FROM pg_stat_activity WHERE usename = '{RUNTIME}' "
                                     "AND state = 'active' AND pid <> pg_backend_pid()", fetch=True)
    assert waiting == [(0,)]
