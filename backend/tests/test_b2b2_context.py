"""M2 B2b-2: two-phase request session context and the app-level harness, on real PostgreSQL 16.

Covers doc 04 "Validation" 3 (pool leak), 4 (interleaving), 5 (rollback/exception), 8 (revocation through the real
path) and 16 (fail-closed layers), and the design's compiled contract C1-C19 (checkpoint design note). Every test
runs through the B2a request-path engine on a provisioned runtime login (INHERIT FALSE members of carvis_app and
carvis_bootstrap), against the B2b-1 schema migrated by a non-superuser CREATEROLE login.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from sqlalchemy import bindparam, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.types import Uuid

import db.context as context
from db.context import (APPROVED_STATEMENTS, SET_APP_ROLE, SET_USER_ID, SET_WORKSPACE_IDS, WORKSPACES_KEY,
                        BootstrapContext, ContextMissing, InactivePrincipal, ProvisionedUser, bootstrap_session,
                        create_request_session_factory, provision, register_listener, tenant_session, unapproved)
from tests.test_b1_migrations import _sql, admin_url, scratch  # noqa: F401
from tests.test_b2a_migrations import migrator  # noqa: F401
from tests.test_b2b1_identity import DB_DO, ISSUER, head, login, violations  # noqa: F401

PING = ";"
FAKE_WS = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
FAKE_USER = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
TENANT_PREFIX = [SET_APP_ROLE, SET_USER_ID, SET_WORKSPACE_IDS]


# --- harness ------------------------------------------------------------------------------------

def run(login_url: str, scenario, pool_size: int = 1, max_overflow: int = 0, pool_timeout: float = 30):
    """Run ``scenario(engine, factory)`` on a fresh request-path engine for the runtime login, then dispose it."""
    from db.engine import create_async_app_engine
    from settings import normalize_database_url

    _, url = normalize_database_url(login_url)

    async def main():
        engine, resolver = create_async_app_engine(url, pool_size=pool_size, max_overflow=max_overflow,
                                                   pool_timeout=pool_timeout)
        try:
            return await scenario(engine, create_request_session_factory(engine))
        finally:
            await engine.dispose()
            resolver.shutdown()

    return asyncio.run(main())


@contextmanager
def captured():
    """Every statement sent through a psycopg async cursor (driver level, includes the pool ping)."""
    statements: list[str] = []
    original = psycopg.AsyncCursor.execute

    async def execute(self, query, params=None, **kwargs):
        statements.append(query if isinstance(query, str) else repr(query))
        return await original(self, query, params, **kwargs)

    psycopg.AsyncCursor.execute = execute
    try:
        yield statements
    finally:
        psycopg.AsyncCursor.execute = original


def sent(statements: list[str]) -> list[str]:
    """Captured statements other than the pool's autocommit liveness ping (outside any transaction)."""
    return [s for s in statements if s != PING]


async def raw_state(engine):
    """``(current_user, app.user_id, app.workspace_ids, backend pid)`` on a raw checkout (no listener)."""
    async with engine.connect() as connection:
        row = (await connection.exec_driver_sql(
            "SELECT current_user, pg_catalog.current_setting('app.user_id', true), "
            "pg_catalog.current_setting('app.workspace_ids', true), pg_catalog.pg_backend_pid()")).one()
        await connection.rollback()
    return tuple(row)


def clean(state, login_name: str = "b1_runtime") -> bool:
    user, user_id, workspace_ids, _ = state
    return user == login_name and user_id in ("", None) and workspace_ids in ("", None)


def memberships_of(scratch, user_id) -> frozenset:
    return frozenset(row[0] for row in _sql(scratch.db_admin, "SELECT workspace_id FROM carvis.memberships "
                                                              f"WHERE user_id = '{user_id}'", fetch=True))


async def warm(engine) -> None:
    """One checkout so SQLAlchemy's first-connect dialect queries are not in later captures."""
    async with engine.connect() as connection:
        await connection.exec_driver_sql("SELECT 1")
        await connection.rollback()


async def read_tenant(session: AsyncSession) -> dict:
    users = {r[0] for r in (await session.execute(text("SELECT id FROM carvis.users"))).all()}
    workspaces = {r[0] for r in (await session.execute(text("SELECT id FROM carvis.workspaces"))).all()}
    members = {tuple(r) for r in (await session.execute(text("SELECT workspace_id, user_id FROM carvis.memberships"))).all()}
    pid = (await session.execute(text("SELECT pg_catalog.pg_backend_pid()"))).scalar()
    return {"users": users, "workspaces": workspaces, "members": members, "pid": pid,
            "key": session.info[WORKSPACES_KEY]}


def boot(subject: str) -> BootstrapContext:
    return BootstrapContext(ISSUER, subject, f"{subject}@example.test")


# --- provisioning (C9) ----------------------------------------------------------------------------

def test_provision_converges_and_returns_status(scratch, login):
    async def scenario(engine, factory):
        first = await provision(factory, boot("user-a"))
        second = await provision(factory, boot("user-a"))
        return first, second

    first, second = run(login, scenario)
    assert first == second and first.status == "active" and isinstance(first.user_id, uuid.UUID)
    assert _sql(scratch.db_admin, "SELECT count(*) FROM carvis.users", fetch=True) == [(1,)]
    assert len(memberships_of(scratch, first.user_id)) == 1


def test_provision_returns_non_active_status_without_rows(scratch, login):
    _sql(scratch.db_admin, f"INSERT INTO carvis.users (auth_issuer, auth_subject, status) "
                           f"VALUES ('{ISSUER}', 'user-d', 'deleting')")

    async def scenario(engine, factory):
        return await provision(factory, boot("user-d"))

    user = run(login, scenario)
    assert user.status == "deleting"
    assert _sql(scratch.db_admin, "SELECT count(*) FROM carvis.workspaces", fetch=True) == [(0,)]
    with pytest.raises(InactivePrincipal):
        tenant_session(None, user)


def test_bootstrap_session_cannot_read_identity_tables(scratch, login):
    async def scenario(engine, factory):
        for table in ("users", "workspaces", "memberships"):
            with pytest.raises(Exception) as caught:
                async with bootstrap_session(factory, boot("user-a")) as session:
                    await session.execute(text(f"SELECT 1 FROM carvis.{table}"))
            assert getattr(caught.value, "orig", None) is not None
            assert caught.value.orig.sqlstate == "42501", table

    run(login, scenario)


def test_bootstrap_is_read_committed_under_a_hostile_default(scratch, login):
    _sql(scratch.db_admin, DB_DO.format("ALTER DATABASE %I SET default_transaction_isolation = ''repeatable read''"))
    try:
        async def scenario(engine, factory):
            async with engine.connect() as connection:  # the hostile default is in effect for new connections
                assert (await connection.exec_driver_sql("SHOW transaction_isolation")).scalar() == "repeatable read"
                await connection.rollback()
            async with bootstrap_session(factory, boot("user-a")) as session:
                level = (await session.execute(text("SHOW transaction_isolation"))).scalar()
            return level, await provision(factory, boot("user-a"))

        level, user = run(login, scenario)
        assert level == "read committed" and user.status == "active"
    finally:
        _sql(scratch.db_admin, DB_DO.format("ALTER DATABASE %I RESET default_transaction_isolation"))


# --- fail-closed layers (C1, C2, C10, C11) --------------------------------------------------------

def test_no_context_refuses_before_any_statement(scratch, login):
    async def scenario(engine, factory):
        await warm(engine)
        with captured() as statements:
            async with factory() as session:
                with pytest.raises(ContextMissing):
                    await session.execute(text("SELECT 1"))
        assert sent(statements) == [], statements
        assert engine.sync_engine.pool.checkedout() == 0
        return await raw_state(engine)

    assert clean(run(login, scenario))


def test_listener_is_registered_once_and_only_on_request_sessions(scratch, login):
    register_listener()
    register_listener()
    assert event.contains(context.RequestSession, "after_begin", context._after_begin)
    assert not event.contains(Session, "after_begin", context._after_begin)

    async def scenario(engine, factory):
        user = await provision(factory, boot("user-a"))
        await warm(engine)
        with captured() as statements:
            async with tenant_session(factory, user):
                pass
        assert sent(statements).count(SET_APP_ROLE) == 1, statements
        with captured() as statements:
            async with AsyncSession(engine) as plain:  # no listener: the raw login holds nothing (C10)
                for table in ("users", "workspaces", "memberships"):
                    with pytest.raises(Exception) as caught:
                        await plain.execute(text(f"SELECT 1 FROM carvis.{table}"))
                    assert caught.value.orig.sqlstate == "42501", table
                    await plain.rollback()
        assert not set(sent(statements)) & set(APPROVED_STATEMENTS)

    run(login, scenario)


def test_role_without_settings_sees_nothing(scratch, login):
    async def scenario(engine, factory):
        user = await provision(factory, boot("user-a"))
        async with engine.connect() as connection:
            await connection.exec_driver_sql(SET_APP_ROLE)
            counts = [(await connection.exec_driver_sql(f"SELECT count(*) FROM carvis.{t}")).scalar()
                      for t in ("users", "workspaces", "memberships")]
            await connection.rollback()
        async with engine.connect() as connection:
            await connection.exec_driver_sql(SET_APP_ROLE)
            await connection.exec_driver_sql(SET_USER_ID, {"user_id": str(user.user_id)})
            workspaces = (await connection.exec_driver_sql("SELECT count(*) FROM carvis.workspaces")).scalar()
            await connection.rollback()
        return counts, workspaces

    counts, workspaces = run(login, scenario)
    assert counts == [0, 0, 0] and workspaces == 0


# --- ordering, readiness, savepoints, non-active (C3, C17, C18, C19, C12) -------------------------

def test_tenant_context_is_installed_in_order_before_the_first_query(scratch, login):
    async def scenario(engine, factory):
        user = await provision(factory, boot("user-a"))
        await warm(engine)
        with captured() as statements:
            async with tenant_session(factory, user) as session:
                await session.execute(text("SELECT 1"))
        return sent(statements)

    assert run(login, scenario) == TENANT_PREFIX + ["SELECT 1"]


def test_workspace_key_is_ready_on_entry_and_cleared_on_exit(scratch, login):
    async def scenario(engine, factory):
        user = await provision(factory, boot("user-a"))
        async with tenant_session(factory, user) as session:
            key = session.info[WORKSPACES_KEY]  # before any request query
        assert WORKSPACES_KEY not in session.info and context.CONTEXT_KEY not in session.info
        try:
            with pytest.raises(ContextMissing):
                await session.execute(text("SELECT 1"))
        finally:
            await session.close()
        assert engine.sync_engine.pool.checkedout() == 0
        return user, key

    user, key = run(login, scenario)
    assert key == memberships_of(scratch, user.user_id) and len(key) == 1


def test_savepoints_do_not_rederive_the_context(scratch, login):
    async def scenario(engine, factory):
        user = await provision(factory, boot("user-a"))
        async with tenant_session(factory, user) as session:
            before = session.info[WORKSPACES_KEY]
            with captured() as statements:
                async with session.begin_nested():
                    await session.execute(text("SELECT 1"))
            assert not set(statements) & set(TENANT_PREFIX), statements
            assert session.info[WORKSPACES_KEY] == before

    run(login, scenario)


def test_non_active_user_never_reaches_a_tenant_transaction(scratch, login):
    async def scenario(engine, factory):
        with captured() as statements:
            with pytest.raises(InactivePrincipal):
                tenant_session(factory, ProvisionedUser(uuid.uuid4(), "deleting"))
        assert statements == []

    run(login, scenario)


def test_contexts_take_typed_values():
    with pytest.raises(TypeError):
        ProvisionedUser("6b1c8f5e-0000-0000-0000-000000000000", "active")
    with pytest.raises(TypeError):
        context.TenantContext("6b1c8f5e-0000-0000-0000-000000000000")
    with pytest.raises(TypeError):
        BootstrapContext(ISSUER, 42)
    with pytest.raises(TypeError):
        tenant_session(None, uuid.uuid4())


# --- transaction scope and pooled reuse (C4, C5, C7; doc 04 Validation 3, 5) ----------------------

def test_pool_reset_policy_is_rollback(scratch, login):
    from sqlalchemy.pool.base import reset_rollback

    async def scenario(engine, factory):
        assert engine.sync_engine.pool._reset_on_return is reset_rollback

    run(login, scenario)


def test_context_does_not_survive_commit_on_the_same_backend(scratch, login):
    async def scenario(engine, factory):
        a = await provision(factory, boot("user-a"))
        b = await provision(factory, boot("user-b"))
        async with tenant_session(factory, a) as session:
            seen_a = await read_tenant(session)
        state = await raw_state(engine)
        async with tenant_session(factory, b) as session:
            seen_b = await read_tenant(session)
        return a, b, seen_a, state, seen_b

    a, b, seen_a, state, seen_b = run(login, scenario)
    assert state[3] == seen_a["pid"] == seen_b["pid"], "pool 1/0 reuses one backend"
    assert clean(state), state
    assert seen_a["users"] == {a.user_id} and seen_b["users"] == {b.user_id}
    assert seen_b["key"] == memberships_of(scratch, b.user_id)


def test_exception_rolls_back_and_clears_the_context(scratch, login):
    async def scenario(engine, factory):
        a = await provision(factory, boot("user-a"))
        with pytest.raises(ZeroDivisionError):
            async with tenant_session(factory, a) as session:
                pid = (await session.execute(text("SELECT pg_catalog.pg_backend_pid()"))).scalar()
                1 / 0
        return pid, await raw_state(engine)

    pid, state = run(login, scenario)
    assert state[3] == pid and clean(state), state


def test_listener_failure_midway_leaves_no_context(scratch, login, monkeypatch):
    async def scenario(engine, factory):
        a = await provision(factory, boot("user-a"))
        monkeypatch.setattr(context, "SET_USER_ID",
                            "SELECT pg_catalog.set_config('app.user_id', %(user_id)s, true), 1 / 0")
        with pytest.raises(Exception) as caught:
            async with tenant_session(factory, a):
                pass
        assert caught.value.orig.sqlstate == "22012"
        assert engine.sync_engine.pool.checkedout() == 0
        return await raw_state(engine)

    assert clean(run(login, scenario))


def test_cancellation_leaves_no_context(scratch, login):
    async def scenario(engine, factory):
        a = await provision(factory, boot("user-a"))
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.5):
                async with tenant_session(factory, a) as session:
                    await session.execute(text("SELECT pg_catalog.pg_sleep(5)"))
        return await raw_state(engine)  # any backend: a cancelled connection may be discarded

    assert clean(run(login, scenario))


# --- concurrency (C6; doc 04 Validation 4) --------------------------------------------------------

def _waiters(engine) -> int | None:
    try:
        return len(engine.sync_engine.pool._pool._queue._getters)
    except AttributeError:  # pragma: no cover - private API changed; the bounded wait below still applies
        return None


def test_contexts_are_per_session_under_controlled_overlap(scratch, login):
    """Both sessions install their contexts and wait on the only connection before either listener runs."""
    async def scenario(engine, factory):
        a = await provision(factory, boot("user-a"))
        b = await provision(factory, boot("user-b"))
        ready = {"a": asyncio.Event(), "b": asyncio.Event()}

        async def request(name, user):
            ready[name].set()
            async with tenant_session(factory, user) as session:
                return await read_tenant(session)

        held = await engine.connect()
        await held.exec_driver_sql("SELECT 1")
        tasks = {"a": asyncio.create_task(request("a", a)), "b": asyncio.create_task(request("b", b))}
        await asyncio.wait_for(asyncio.gather(ready["a"].wait(), ready["b"].wait()), 5)
        for _ in range(100):  # bounded: both tasks must be queued on checkout before the connection is released
            if _waiters(engine) == 2:
                break
            await asyncio.sleep(0.02)
        assert _waiters(engine) in (2, None)
        await held.rollback()
        await held.close()
        return a, b, await tasks["a"], await tasks["b"]

    a, b, seen_a, seen_b = run(login, scenario)
    assert seen_a["users"] == {a.user_id} and seen_a["key"] == memberships_of(scratch, a.user_id)
    assert seen_b["users"] == {b.user_id} and seen_b["key"] == memberships_of(scratch, b.user_id)


def test_interleaved_two_phase_requests_never_cross_read(scratch, login):
    async def scenario(engine, factory):
        limit = asyncio.Semaphore(20)

        async def request(i):
            async with limit:
                user = await provision(factory, boot("user-a" if i % 2 == 0 else "user-b"))
                async with tenant_session(factory, user) as session:
                    if i % 3 == 0:
                        await asyncio.sleep(0)
                    return user, await read_tenant(session)

        return await asyncio.gather(*(request(i) for i in range(200)))

    results = run(login, scenario, pool_size=2, max_overflow=0, pool_timeout=60)
    expected = {}
    pids = {}
    for user, seen in results:
        expected.setdefault(user.user_id, memberships_of(scratch, user.user_id))
        assert seen["users"] == {user.user_id}
        assert seen["key"] == expected[user.user_id] == seen["workspaces"]
        assert {m[1] for m in seen["members"]} == {user.user_id}
        pids.setdefault(user.user_id, set()).add(seen["pid"])
    assert len(expected) == 2
    first, second = pids.values()
    assert first & second, "at least one backend served both users"


# --- derivation and revocation (C8; doc 04 Validation 8) -----------------------------------------

def test_revocation_applies_to_the_next_transaction(scratch, login):
    async def scenario(engine, factory):
        a = await provision(factory, boot("user-a"))
        personal = next(iter(memberships_of(scratch, a.user_id)))
        shop = _sql(scratch.db_admin, "INSERT INTO carvis.workspaces (kind, name) VALUES ('shop', 'Shop') "
                                      "RETURNING id", fetch=True)[0][0]
        _sql(scratch.db_admin, f"INSERT INTO carvis.memberships VALUES ('{shop}', '{a.user_id}', 'member')")
        keys = []
        async with tenant_session(factory, a) as session:
            keys.append(session.info[WORKSPACES_KEY])
        _sql(scratch.db_admin, f"DELETE FROM carvis.memberships WHERE workspace_id = '{shop}'")
        async with tenant_session(factory, a) as session:
            keys.append(session.info[WORKSPACES_KEY])
        _sql(scratch.db_admin, f"DELETE FROM carvis.memberships WHERE user_id = '{a.user_id}'")
        async with tenant_session(factory, a) as session:
            keys.append(session.info[WORKSPACES_KEY])
            setting = (await session.execute(
                text("SELECT pg_catalog.current_setting('app.workspace_ids', true)"))).scalar()
            rows = (await session.execute(text("SELECT count(*) FROM carvis.workspaces"))).scalar()
        return personal, shop, keys, setting, rows

    personal, shop, keys, setting, rows = run(login, scenario)
    assert keys == [frozenset({personal, shop}), frozenset({personal}), frozenset()]
    assert setting == "{}" and rows == 0


def test_harness_creates_no_privileges(scratch, login):
    async def scenario(engine, factory):
        user = await provision(factory, boot("user-a"))
        async with tenant_session(factory, user) as session:
            await read_tenant(session)

    run(login, scenario)
    assert violations(scratch.db_admin) == []


# --- names: hostile search_path (C14) ------------------------------------------------------------

SHADOW = [
    "CREATE SCHEMA rv_shadow",
    "CREATE FUNCTION rv_shadow.boom(pg_catalog.text) RETURNS boolean LANGUAGE plpgsql "
    "AS $$BEGIN RAISE EXCEPTION 'shadow text used'; END$$",
    "CREATE DOMAIN rv_shadow.text AS pg_catalog.text CHECK (rv_shadow.boom(VALUE))",
    "CREATE FUNCTION rv_shadow.set_config(pg_catalog.text, pg_catalog.text, boolean) RETURNS pg_catalog.text "
    "LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'shadow set_config used'; END$$",
    "CREATE FUNCTION rv_shadow.fake_step(pg_catalog.uuid[], pg_catalog.uuid) RETURNS pg_catalog.uuid[] "
    f"LANGUAGE sql AS $$SELECT ARRAY['{FAKE_WS}'::pg_catalog.uuid]$$",
    "CREATE AGGREGATE rv_shadow.array_agg(pg_catalog.uuid) (SFUNC = rv_shadow.fake_step, STYPE = pg_catalog.uuid[])",
    "CREATE TABLE rv_shadow.memberships (workspace_id pg_catalog.uuid, user_id pg_catalog.uuid, role pg_catalog.text)",
    "CREATE FUNCTION rv_shadow.ensure_principal(pg_catalog.text, pg_catalog.text, pg_catalog.text) "
    "RETURNS TABLE (user_id pg_catalog.uuid, status pg_catalog.text) LANGUAGE sql "
    f"AS $$SELECT '{FAKE_USER}'::pg_catalog.uuid, 'active'::pg_catalog.text$$",
    "GRANT USAGE ON SCHEMA rv_shadow TO carvis_app, carvis_bootstrap",
    "GRANT USAGE ON TYPE rv_shadow.text TO carvis_app, carvis_bootstrap",
    "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rv_shadow TO carvis_app, carvis_bootstrap",
    "GRANT SELECT ON rv_shadow.memberships TO carvis_app",
]

# Each look-alike must be what an unqualified name would reach, as the role that would run it.
PREFLIGHT = [
    ("carvis_app", "SELECT 'x'::text", "shadow text used"),
    ("carvis_app", "SELECT set_config('app.x', 'y', true)", "shadow set_config used"),
    ("carvis_app", f"SELECT array_agg(v) FROM (VALUES ('{uuid.uuid4()}'::pg_catalog.uuid)) AS t(v)", [FAKE_WS]),
    ("carvis_app", "SELECT workspace_id FROM memberships", FAKE_WS),
    ("carvis_bootstrap", "SELECT user_id FROM ensure_principal('i', 's', NULL)", FAKE_USER),
]


async def _preflight(engine, role: str, sql: str, expected):
    async with engine.connect() as connection:
        await connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        try:
            if isinstance(expected, str):
                with pytest.raises(Exception, match=expected):
                    await connection.exec_driver_sql(sql)
            else:
                assert (await connection.exec_driver_sql(sql)).scalar() == expected, sql
        finally:
            await connection.rollback()


def test_hostile_search_path_resolves_nothing(scratch, login):
    real = {}

    async def setup(engine, factory):
        real["a"] = await provision(factory, boot("user-a"))

    run(login, setup)
    real_key = memberships_of(scratch, real["a"].user_id)
    _sql(scratch.db_admin, *SHADOW, f"INSERT INTO rv_shadow.memberships VALUES ('{FAKE_WS}', '{real['a'].user_id}', 'owner')")
    _sql(scratch.db_admin, DB_DO.format("ALTER DATABASE %I SET search_path = rv_shadow, pg_catalog"))
    try:
        async def scenario(engine, factory):
            async with engine.connect() as connection:
                assert (await connection.exec_driver_sql("SHOW search_path")).scalar() == "rv_shadow, pg_catalog"
                await connection.rollback()
            for role, sql, expected in PREFLIGHT:
                await _preflight(engine, role, sql, expected)
            user = await provision(factory, boot("user-a"))
            async with tenant_session(factory, user) as session:
                key = session.info[WORKSPACES_KEY]
                setting = (await session.execute(
                    text("SELECT pg_catalog.current_setting('app.workspace_ids', true)"))).scalar()
            return user, key, setting

        user, key, setting = run(login, scenario)
        assert user == real["a"]
        assert key == real_key and setting == "{" + ",".join(str(w) for w in real_key) + "}"
    finally:
        _sql(scratch.db_admin, DB_DO.format("ALTER DATABASE %I RESET search_path"), "DROP SCHEMA rv_shadow CASCADE")


def test_temp_schema_relation_is_never_used(scratch, login):
    real = {}

    async def setup(engine, factory):
        real["a"] = await provision(factory, boot("user-a"))

    run(login, setup)
    real_key = memberships_of(scratch, real["a"].user_id)
    _sql(scratch.db_admin, DB_DO.format("ALTER DATABASE %I SET search_path = pg_temp, pg_catalog"))
    try:
        async def scenario(engine, factory):  # pool 1/0: the temp table lives on the backend the session uses
            async with engine.connect() as connection:
                await connection.exec_driver_sql(
                    "CREATE TEMP TABLE memberships (workspace_id pg_catalog.uuid, user_id pg_catalog.uuid, "
                    "role pg_catalog.text)")
                await connection.exec_driver_sql(
                    f"INSERT INTO pg_temp.memberships VALUES ('{FAKE_WS}', '{real['a'].user_id}', 'owner')")
                await connection.exec_driver_sql("GRANT SELECT ON pg_temp.memberships TO carvis_app")
                await connection.commit()
            await _preflight(engine, "carvis_app", "SELECT workspace_id FROM memberships", FAKE_WS)
            async with tenant_session(factory, real["a"]) as session:
                return session.info[WORKSPACES_KEY]

        assert run(login, scenario) == real_key
    finally:
        _sql(scratch.db_admin, DB_DO.format("ALTER DATABASE %I RESET search_path"))


# --- C14b: the closed statement allow-list ---------------------------------------------------------

KEYWORDS = {"SELECT", "FROM", "AS", "SET", "LOCAL", "ROLE", "TRANSACTION", "ISOLATION", "LEVEL", "READ",
            "COMMITTED", "COALESCE", "true"}
NAMES = {"carvis_bootstrap", "carvis_app", "p", "m", "p.user_id", "p.status", "m.workspace_id",
         "carvis.memberships", "carvis.ensure_principal", "pg_catalog.set_config", "pg_catalog.array_agg",
         "pg_catalog.text"}
TOKEN = re.compile(r"\s+|'(?:[^']|'')*'|%\(\w+\)s|::|[(),]|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?|.")


def disallowed_tokens(statement: str) -> list[str]:
    """Allow-list tokenizer: anything that is not whitespace, a literal, a placeholder, ``( ) , ::``, a listed
    keyword or a listed name is returned (fail closed)."""
    bad = []
    for match in TOKEN.finditer(statement):
        token = match.group(0)
        if token.isspace() or token.startswith("'") or token.startswith("%(") or token in {"(", ")", ",", "::"}:
            continue
        if token in KEYWORDS or token in NAMES:
            continue
        bad.append(token)
    return bad


def test_approved_statements_use_only_qualified_names_and_no_operators():
    for statement in APPROVED_STATEMENTS:
        assert disallowed_tokens(statement) == [], statement


def test_emitted_sql_is_exactly_the_approved_statements(scratch, login):
    async def scenario(engine, factory):
        await warm(engine)
        with captured() as statements:
            user = await provision(factory, boot("user-a"))
            async with tenant_session(factory, user):
                pass
        return sent(statements)

    emitted = run(login, scenario)
    assert unapproved(emitted) == [], emitted
    assert set(emitted) == set(APPROVED_STATEMENTS)


def _typed_bind_rendering() -> str:
    from sqlalchemy.dialects.postgresql.psycopg import dialect

    statement = text("SELECT pg_catalog.set_config('app.user_id', :user_id, true)").bindparams(
        bindparam("user_id", type_=Uuid))
    return str(statement.compile(dialect=dialect()))


@pytest.mark.parametrize("statement", [
    SET_WORKSPACE_IDS + " WHERE m.user_id = %(user_id)s",
    SET_WORKSPACE_IDS.replace("pg_catalog.array_agg(m.workspace_id)::pg_catalog.text",
                              "CAST(pg_catalog.array_agg(m.workspace_id) AS text)"),
    "generated",
], ids=["operator", "cast", "generated-bind-cast"])
def test_c14b_rejects_unsupported_constructs(statement):
    if statement == "generated":
        statement = _typed_bind_rendering()
        assert "::UUID" in statement, statement
    assert unapproved([statement]) == [statement]
    assert disallowed_tokens(statement), statement
