"""M2 B2a: explicit connection rules (B1 deferred N2 and N3), the shared request-path resolver and the
bounded async engine.

The rule and resolver tests need no database. The engine tests use real PostgreSQL 16 through
``CARVIS_TEST_POSTGRES_URL`` (skipped without it, failing under ``CARVIS_REQUIRE_POSTGRES=1``).
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest

from db.conninfo import ConnectionConfigError, host_port_entries, reject_service_files, validate_conninfo
from db.readiness import (DATABASE_MISCONFIGURED, ReadinessProbe, ResolverBusy, connection_attempts, postgres_fetch)
from settings import normalize_database_url

# --- N2: host/port counts follow libpq ------------------------------------------------------------


@pytest.mark.parametrize("params,environ,expected", [
    ({"host": "a,b", "port": "1,2"}, {}, [("a", "1"), ("b", "2")]),
    ({"host": "a,b", "port": "7"}, {}, [("a", "7"), ("b", "7")]),
    ({"host": "a,b"}, {}, [("a", "5432"), ("b", "5432")]),
    ({}, {"PGHOST": "a,b", "PGPORT": "1,2"}, [("a", "1"), ("b", "2")]),
    ({"host": "a"}, {"PGPORT": "9"}, [("a", "9")]),
    ({"host": "a,b", "port": "1,"}, {}, [("a", "1"), ("b", "5432")]),
])
def test_valid_host_port_counts(params, environ, expected):
    assert host_port_entries(params, environ) == expected


@pytest.mark.parametrize("params,environ", [
    ({"host": "a,b,c", "port": "1,2"}, {}),
    ({"host": "a", "port": "1,2"}, {}),
    ({}, {"PGHOST": "a,b,c", "PGPORT": "1,2"}),
    ({"host": "a,b,c"}, {"PGPORT": "1,2"}),
    ({}, {"PGPORT": "1,2"}),  # default socket host, two ports
])
def test_mismatched_host_port_counts_are_rejected(params, environ):
    with pytest.raises(ConnectionConfigError, match="number of ports"):
        host_port_entries(params, environ)


def test_settings_mark_env_driven_mismatch_invalid(monkeypatch):
    monkeypatch.setenv("PGHOST", "db1.test,db2.test,db3.test")
    monkeypatch.setenv("PGPORT", "5432,5433")
    status, url = normalize_database_url("postgresql://u:p@/carvis")
    assert (status, url) == ("invalid", None)


def test_settings_accept_valid_env_hosts(monkeypatch):
    monkeypatch.setenv("PGHOST", "db1.test,db2.test")
    monkeypatch.setenv("PGPORT", "5432,5433")
    assert normalize_database_url("postgresql://u:p@/carvis")[0] == "configured"


def test_readiness_never_guesses_a_port(monkeypatch):
    """B1 used the first port for every host on a mismatch; B2a refuses (N2)."""
    monkeypatch.setenv("PGHOST", "db1.test,db2.test,db3.test")
    monkeypatch.setenv("PGPORT", "5432,5433")

    class Resolver:
        async def resolve(self, host, port):  # pragma: no cover - must not be reached
            raise AssertionError("no lookup may start for a misconfigured host list")

    with pytest.raises(ConnectionConfigError):
        asyncio.run(connection_attempts("postgresql://u:p@/carvis", Resolver()))
    probe = ReadinessProbe("head", postgres_fetch("postgresql://u:p@/carvis", Resolver(), 1.0), 1.0)
    assert asyncio.run(probe.check()).reason == DATABASE_MISCONFIGURED


# --- N3: service files are refused ----------------------------------------------------------------

@pytest.mark.parametrize("params,environ", [
    ({"service": "carvis"}, {}),
    ({"servicefile": "/etc/pg_service.conf"}, {}),
    ({}, {"PGSERVICE": "carvis"}),
    ({}, {"PGSERVICEFILE": "/tmp/x.conf"}),
])
def test_service_files_are_refused(params, environ):
    with pytest.raises(ConnectionConfigError, match="(?i)service"):
        reject_service_files(params, environ)


def test_settings_reject_service_url_and_variables(monkeypatch):
    assert normalize_database_url("postgresql://u:p@db.test/carvis?service=carvis")[0] == "invalid"
    monkeypatch.setenv("PGSERVICE", "carvis")
    assert normalize_database_url("postgresql://u:p@db.test/carvis")[0] == "invalid"


def test_readiness_refuses_service_file_before_any_lookup(monkeypatch):
    monkeypatch.setenv("PGSERVICEFILE", "/tmp/pg_service.conf")

    class Resolver:
        async def resolve(self, host, port):  # pragma: no cover
            raise AssertionError("no lookup")

    probe = ReadinessProbe("head", postgres_fetch("postgresql://u:p@db.test/carvis", Resolver(), 1.0), 1.0)
    assert asyncio.run(probe.check()).reason == DATABASE_MISCONFIGURED


def test_validate_conninfo_never_echoes_the_string():
    with pytest.raises(ConnectionConfigError) as error:
        validate_conninfo("host=a,b port=1,2,3 password=Sup3rSecret")
    assert "Sup3rSecret" not in str(error.value)


def test_settings_refuse_boot_outside_local_on_mismatch(monkeypatch):
    from settings import DatabaseConfigurationError, load_settings

    for name, value in {"CARVIS_ENV": "production", "VAPI_WEBHOOK_SECRET": "s", "CARVIS_DEFAULT_SHOP_ID": "shop",
                        "CARVIS_QDRANT_COLLECTION": "carvis_specs_v2", "PGPORT": "1,2",
                        "CARVIS_DATABASE_URL": "postgresql://u:p@/carvis?host=a,b,c"}.items():
        monkeypatch.setenv(name, value)
    for name in ("SPACETIMEDB_URI", "SPACETIMEDB_TOKEN", "SPACETIMEDB_DB_NAME", "RENDER"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(DatabaseConfigurationError):
        load_settings()


# --- SharedResolver -------------------------------------------------------------------------------

@pytest.fixture
def slow_dns(monkeypatch):
    """``db.slow.test`` answers 127.0.0.1 after 0.3 s; ``db.stalled.test`` blocks until teardown."""
    real = socket.getaddrinfo
    release = threading.Event()
    calls: list[str] = []

    def fake(host, port, *args, **kwargs):
        if host in ("db.slow.test", "db.stalled.test"):
            calls.append(host)
            if host == "db.stalled.test":
                release.wait(30)
            else:
                time.sleep(0.3)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", int(port)))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    yield calls
    release.set()


def test_concurrent_lookups_share_one_inflight_lookup(slow_dns):
    from db.engine import SharedResolver

    resolver = SharedResolver()

    async def scenario():
        return await asyncio.gather(*(resolver.resolve("db.slow.test", "5432") for _ in range(8)))

    try:
        results = asyncio.run(scenario())
    finally:
        resolver.shutdown()
    assert results == [["127.0.0.1"]] * 8
    assert slow_dns == ["db.slow.test"] and resolver.lookups_started == 1


def test_cached_answer_needs_no_new_lookup_until_expiry(slow_dns):
    from db.engine import SharedResolver

    now = [0.0]
    resolver = SharedResolver(cache_seconds=30.0, clock=lambda: now[0])
    try:
        asyncio.run(resolver.resolve("db.slow.test", "5432"))
        asyncio.run(resolver.resolve("db.slow.test", "5432"))
        assert resolver.lookups_started == 1
        now[0] = 31.0
        asyncio.run(resolver.resolve("db.slow.test", "5432"))
        assert resolver.lookups_started == 2
    finally:
        resolver.shutdown()


def test_cancelled_waiter_does_not_cancel_the_shared_lookup(slow_dns):
    from db.engine import SharedResolver

    resolver = SharedResolver()

    async def scenario():
        impatient = asyncio.create_task(resolver.resolve("db.slow.test", "5432"))
        patient = asyncio.create_task(resolver.resolve("db.slow.test", "5432"))
        await asyncio.sleep(0.05)
        impatient.cancel()
        return await patient

    try:
        assert asyncio.run(scenario()) == ["127.0.0.1"]
    finally:
        resolver.shutdown()


def test_stalled_lookups_are_bounded_by_the_pool(slow_dns):
    from db.engine import SharedResolver

    resolver = SharedResolver(threads=1)

    async def scenario():
        stalled = asyncio.create_task(resolver.resolve("db.stalled.test", "5432"))
        await asyncio.sleep(0.05)
        with pytest.raises(ResolverBusy):
            await resolver.resolve("db.other.test", "5432")
        # A second caller for the stalled name joins the same lookup instead of starting another.
        joined = asyncio.create_task(resolver.resolve("db.stalled.test", "5432"))
        await asyncio.sleep(0.05)
        stalled.cancel(), joined.cancel()
        return resolver.lookups_started

    try:
        assert asyncio.run(scenario()) == 1
    finally:
        resolver.shutdown()


def test_resolver_never_uses_the_default_executor(slow_dns, monkeypatch):
    from db.engine import SharedResolver

    def forbidden(self, *args, **kwargs):  # pragma: no cover - failing path
        raise AssertionError("the shared default executor must not be used")

    monkeypatch.setattr(asyncio.BaseEventLoop, "run_in_executor", forbidden)
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", forbidden)
    resolver = SharedResolver()
    try:
        assert asyncio.run(resolver.resolve("db.slow.test", "5432")) == ["127.0.0.1"]
    finally:
        resolver.shutdown()


# --- Async engine on real PostgreSQL --------------------------------------------------------------

@pytest.fixture
def pg_url():
    from tests.test_b1_migrations import ADMIN_URL, REQUIRED

    if not ADMIN_URL:
        if REQUIRED:
            pytest.fail("CARVIS_REQUIRE_POSTGRES=1 but CARVIS_TEST_POSTGRES_URL is not set")
        pytest.skip("CARVIS_TEST_POSTGRES_URL not set")
    return ADMIN_URL


def _named(admin: str, host: str) -> str:
    from sqlalchemy.engine import make_url

    url = make_url(admin)
    return url.set(host=host, query={**url.query, "sslmode": "disable"}).render_as_string(hide_password=False)


def test_async_engine_runs_a_query_through_the_bounded_creator(pg_url, slow_dns, monkeypatch):
    from sqlalchemy import text

    from db.engine import create_async_app_engine

    def forbidden(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("psycopg must not resolve names on the event loop's executor")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", forbidden)
    _, url = normalize_database_url(_named(pg_url, "db.slow.test"))
    engine, resolver = create_async_app_engine(url)

    async def scenario():
        async def one():
            async with engine.connect() as connection:
                return (await connection.execute(text("SELECT 1"))).scalar()

        try:
            return await asyncio.gather(*(one() for _ in range(6)))  # cold pool, concurrent first checkouts
        finally:
            await engine.dispose()

    try:
        assert asyncio.run(scenario()) == [1] * 6
    finally:
        resolver.shutdown()
    assert resolver.lookups_started == 1, "concurrent pool fills share one lookup"


def test_async_engine_connect_is_bounded_when_dns_stalls(pg_url, slow_dns):
    from sqlalchemy import text

    from db.engine import create_async_app_engine

    _, url = normalize_database_url(_named(pg_url, "db.stalled.test"))
    engine, resolver = create_async_app_engine(url, connect_deadline_seconds=0.5)

    async def scenario():
        started = time.monotonic()
        try:
            async with asyncio.timeout(3):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - any failure is acceptable; it must be prompt
            return type(exc).__name__, time.monotonic() - started
        finally:
            await engine.dispose()
        return "connected", time.monotonic() - started

    try:
        outcome, elapsed = asyncio.run(scenario())
    finally:
        resolver.shutdown()
    assert outcome != "connected"
    assert elapsed < 1.5, (outcome, elapsed)  # the 0.5 s connect deadline, not the 3 s guard


def test_cancelled_waiter_does_not_cancel_a_queued_shared_lookup(slow_dns):
    """A lookup still queued (not running) must survive one waiter's cancellation."""
    from concurrent.futures import ThreadPoolExecutor

    from db.engine import SharedResolver

    resolver = SharedResolver(threads=2)
    resolver._executor.shutdown(wait=False)
    resolver._executor = ThreadPoolExecutor(max_workers=1)
    gate = threading.Event()
    resolver._executor.submit(gate.wait, 5)  # occupies the only worker, so the next lookup queues

    async def scenario():
        impatient = asyncio.create_task(resolver.resolve("db.slow.test", "5432"))
        patient = asyncio.create_task(resolver.resolve("db.slow.test", "5432"))
        await asyncio.sleep(0.05)
        impatient.cancel()
        await asyncio.sleep(0.05)
        gate.set()
        return await patient

    try:
        assert asyncio.run(scenario()) == ["127.0.0.1"]
    finally:
        gate.set()
        resolver.shutdown()


# --- Round-2 review: hostaddr takes part in libpq's count rule --------------------------------------

@pytest.mark.parametrize("params,environ,expected", [
    ({"hostaddr": "127.0.0.1,127.0.0.2", "port": "5432,5433"}, {}, [("", "5432"), ("", "5433")]),
    ({"host": "a,b", "hostaddr": "127.0.0.1,127.0.0.2", "port": "5432,5433"}, {}, [("a", "5432"), ("b", "5433")]),
    ({"hostaddr": "127.0.0.1,127.0.0.2", "port": "5432"}, {}, [("", "5432"), ("", "5432")]),
    ({}, {"PGHOSTADDR": "127.0.0.1,127.0.0.2", "PGPORT": "1,2"}, [("", "1"), ("", "2")]),
])
def test_valid_hostaddr_lists_are_accepted(params, environ, expected):
    assert host_port_entries(params, environ) == expected


@pytest.mark.parametrize("params,environ", [
    ({"host": "a,b", "hostaddr": "127.0.0.1", "port": "1,2"}, {}),
    ({"host": "a", "hostaddr": "127.0.0.1,127.0.0.2"}, {}),
    ({}, {"PGHOST": "a,b", "PGHOSTADDR": "127.0.0.1"}),
    ({"hostaddr": "127.0.0.1,127.0.0.2", "port": "1,2,3"}, {}),
])
def test_mismatched_hostaddr_lists_are_refused(params, environ):
    with pytest.raises(ConnectionConfigError):
        host_port_entries(params, environ)


def test_settings_accept_hostaddr_only_and_refuse_mismatch():
    assert normalize_database_url("postgresql://u:p@/carvis?hostaddr=127.0.0.1,127.0.0.2&port=5432,5433",
                                  environ={})[0] == "configured"
    assert normalize_database_url("postgresql://u:p@/carvis?host=a,b&hostaddr=127.0.0.1&port=1,2",
                                  environ={})[0] == "invalid"


def test_readiness_reports_mismatched_hostaddr_as_misconfigured():
    class Resolver:
        async def resolve(self, host, port):  # pragma: no cover
            raise AssertionError("no lookup")

    url = "postgresql://u:p@/carvis?host=a.test,b.test&hostaddr=127.0.0.1&port=1,2"
    probe = ReadinessProbe("head", postgres_fetch(url, Resolver(), 1.0), 1.0)
    assert asyncio.run(probe.check()).reason == DATABASE_MISCONFIGURED


# --- Round-3 review: every interpreted libpq parameter honors its environment variable --------------

class _NoLookups:
    lookups: list = []

    async def resolve(self, host, port):  # pragma: no cover - failing path
        raise AssertionError("an explicit PGHOSTADDR needs no lookup")


def test_pghostaddr_environment_is_used_without_lookup(monkeypatch):
    monkeypatch.setenv("PGHOSTADDR", "127.0.0.1")
    conninfo = "host=unresolvable.invalid port=5432 dbname=carvis"
    assert asyncio.run(connection_attempts(conninfo, _NoLookups())) == [conninfo]


def test_pgloadbalancehosts_environment_shuffles_hosts(monkeypatch):
    import random

    order: list[str] = []

    class Resolver:
        async def resolve(self, host, port):
            order.append(host)
            return ["192.0.2.10"]

    monkeypatch.setenv("PGLOADBALANCEHOSTS", "random")
    monkeypatch.setattr(random, "shuffle", lambda items: items.reverse())
    asyncio.run(connection_attempts("host=a.test,b.test,c.test port=5432", Resolver()))
    assert order == ["c.test", "b.test", "a.test"]


def test_pghostaddr_readiness_and_engine_on_real_postgres(pg_url, monkeypatch):
    """libpq connects to PGHOSTADDR and keeps the (unresolvable) host name; CARVIS must do the same."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from db.engine import create_async_app_engine
    from db.readiness import READY, BoundedResolver

    admin = make_url(pg_url)
    monkeypatch.setenv("PGHOSTADDR", admin.host)
    url = admin.set(host="unresolvable.invalid", query={**admin.query, "sslmode": "disable"})
    conninfo = url.set(drivername="postgresql").render_as_string(hide_password=False)

    class Resolver(BoundedResolver):
        async def resolve(self, host, port):  # pragma: no cover - failing path
            raise AssertionError("no lookup")

    # Readiness reaches the server through PGHOSTADDR (the version table may not exist: pending is fine,
    # unreachable or misconfigured is not).
    probe = ReadinessProbe("head", postgres_fetch(conninfo, Resolver(), 2.0, enforce_login=False), 2.0)
    assert asyncio.run(probe.check()).reason in (READY, "migrations_pending")

    _, database_url = normalize_database_url(url.render_as_string(hide_password=False))
    engine, resolver = create_async_app_engine(database_url)

    async def scenario():
        try:
            async with engine.connect() as connection:
                return (await connection.execute(text("SELECT 1"))).scalar()
        finally:
            await engine.dispose()

    try:
        assert asyncio.run(scenario()) == 1
    finally:
        resolver.shutdown()
    assert resolver.lookups_started == 0
