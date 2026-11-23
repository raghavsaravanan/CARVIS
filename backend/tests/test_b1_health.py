"""M2 B1: /healthz, /readyz and the bounded single-flight readiness probe.

The probe tests use fake fetches and local TCP peers that never answer; nothing contacts a provider.
Real-PostgreSQL readiness is covered in ``test_b1_migrations.py``.
"""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

import main
from db.readiness import (DATABASE_MISCONFIGURED, DATABASE_UNCONFIGURED, DATABASE_UNREACHABLE, MIGRATIONS_PENDING,
                          READY, STARTING, ReadinessProbe, expected_head, postgres_fetch)
from settings import Settings, normalize_database_url

HEAD = expected_head()


@pytest.fixture
def client():
    # Without the lifespan, /readyz reads whatever probe app.state holds; restore it afterwards.
    original = getattr(main.app.state, "readiness", None)
    main.app.state.readiness = None
    yield TestClient(main.app)
    main.app.state.readiness = original


def set_probe(_monkeypatch, probe):
    main.app.state.readiness = probe


def fetch_returning(revisions):
    async def fetch():
        return list(revisions)
    return fetch


def test_healthz_needs_no_dependency(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_legacy_health_is_unchanged(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.content == b'{"status":"ok","service":"carvis"}'


def test_readyz_before_startup_is_not_ready(client):
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "reason": STARTING}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("status,reason", [("unconfigured", DATABASE_UNCONFIGURED),
                                           ("invalid", DATABASE_MISCONFIGURED)])
def test_missing_or_invalid_database_is_never_ready(client, monkeypatch, status, reason):
    settings = Settings(environment="local", database_status=status, database_url=None)
    set_probe(monkeypatch, ReadinessProbe.from_settings(settings, HEAD))
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "reason": reason}


def test_ready_only_at_head(client, monkeypatch):
    set_probe(monkeypatch, ReadinessProbe(HEAD, fetch_returning([HEAD]), 1.0))
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.parametrize("revisions", [[], ["0001_baseline"], ["unknown_future"], [HEAD, HEAD]])
def test_not_at_head_is_pending(client, monkeypatch, revisions):
    set_probe(monkeypatch, ReadinessProbe(HEAD, fetch_returning(revisions), 1.0))
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["reason"] == MIGRATIONS_PENDING


class _SqlError(Exception):
    def __init__(self, sqlstate):
        super().__init__("relation \"carvis_migrations.alembic_version\" at db.internal for user secret_user")
        self.sqlstate = sqlstate


@pytest.mark.parametrize("sqlstate,reason", [("42P01", MIGRATIONS_PENDING), ("3F000", MIGRATIONS_PENDING),
                                             ("42501", DATABASE_UNREACHABLE), (None, DATABASE_UNREACHABLE)])
def test_failures_map_to_fixed_codes_without_detail(client, monkeypatch, caplog, sqlstate, reason):
    async def fetch():
        raise _SqlError(sqlstate)

    set_probe(monkeypatch, ReadinessProbe(HEAD, fetch, 1.0))
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "reason": reason}
    assert "secret_user" not in response.text and "db.internal" not in response.text
    assert "secret_user" not in caplog.text and "db.internal" not in caplog.text


def test_hung_fetch_is_cut_off_at_the_deadline():
    cancelled = asyncio.Event()

    async def fetch():
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    probe = ReadinessProbe(HEAD, fetch, 0.2)

    async def scenario():
        started = time.monotonic()
        result = await probe.check()
        return result, time.monotonic() - started, cancelled.is_set()

    result, elapsed, was_cancelled = asyncio.run(scenario())
    assert result.reason == DATABASE_UNREACHABLE
    assert elapsed < 1.0
    assert was_cancelled, "the hung fetch must be cancelled, not left running"


def test_concurrent_checks_share_one_probe():
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(3600)

    probe = ReadinessProbe(HEAD, fetch, 0.3)

    async def scenario():
        before = {t for t in asyncio.all_tasks()}
        results = await asyncio.gather(*(probe.check() for _ in range(50)))
        leftover = {t for t in asyncio.all_tasks() if not t.done()} - before - {asyncio.current_task()}
        return results, leftover

    results, leftover = asyncio.run(scenario())
    assert {r.reason for r in results} == {DATABASE_UNREACHABLE}
    assert calls == 1 and probe.probes_started == 1
    assert not leftover


def test_cancelled_waiter_does_not_cancel_shared_probe():
    finished = asyncio.Event()

    async def fetch():
        await asyncio.sleep(0.1)
        finished.set()
        return [HEAD]

    probe = ReadinessProbe(HEAD, fetch, 1.0)

    async def scenario():
        waiter = asyncio.ensure_future(probe.check())
        await asyncio.sleep(0.01)
        waiter.cancel()
        result = await probe.check()
        return result, finished.is_set()

    result, done = asyncio.run(scenario())
    assert result.reason == READY and done


def test_no_threads_are_started_by_a_probe():
    async def fetch():
        await asyncio.sleep(3600)

    probe = ReadinessProbe(HEAD, fetch, 0.1)
    before = threading.active_count()
    asyncio.run(probe.check())
    assert threading.active_count() <= before


def _silent_peer(forward_to=None, forward_bytes=None):
    """A TCP listener that accepts and reads but never answers (or forwards a prefix, then stops)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    stop = threading.Event()
    held = []

    def serve():
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            held.append(conn)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    def close():
        stop.set()
        thread.join()
        for conn in held:
            conn.close()
        server.close()

    return server.getsockname()[1], close


def test_real_driver_against_a_peer_that_never_answers():
    """psycopg's async connect to a socket that accepts and acknowledges but never replies is cut off."""
    port, close = _silent_peer()
    try:
        status, url = normalize_database_url(f"postgresql://carvis:pw@127.0.0.1:{port}/carvis?sslmode=disable")
        assert status == "configured"
        from db.engine import libpq_conninfo

        probe = ReadinessProbe(HEAD, postgres_fetch(libpq_conninfo(url)), 0.5)

        async def scenario():
            started = time.monotonic()
            results = await asyncio.gather(*(probe.check() for _ in range(10)))
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
            return results, time.monotonic() - started, pending

        before = threading.active_count()
        results, elapsed, pending = asyncio.run(scenario())
        assert {r.reason for r in results} == {DATABASE_UNREACHABLE}
        assert elapsed < 1.5
        assert probe.probes_started == 1
        assert not pending
        assert threading.active_count() <= before
    finally:
        close()


def test_close_cancels_inflight_probe():
    async def fetch():
        await asyncio.sleep(3600)

    probe = ReadinessProbe(HEAD, fetch, 60)

    async def scenario():
        waiter = asyncio.ensure_future(probe.check())
        await asyncio.sleep(0.01)
        await probe.close()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    asyncio.run(asyncio.wait_for(scenario(), 2))


# --- Host-name resolution (round-1 review: DNS lookups must not accumulate threads) ----------------

@pytest.fixture
def stalled_dns(monkeypatch):
    """socket.getaddrinfo blocks for one host name until released; every call is counted."""
    import socket as socket_module

    release = threading.Event()
    calls = []
    real = socket_module.getaddrinfo

    def fake(host, *args, **kwargs):
        if host == "db.stalled.invalid":
            calls.append(host)
            release.wait(30)
            return real("127.0.0.1", *args, **kwargs)
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket_module, "getaddrinfo", fake)
    yield calls, release
    release.set()


def test_stalled_dns_never_accumulates_threads_or_blocks_the_default_executor(stalled_dns):
    from db.readiness import BoundedResolver

    calls, release = stalled_dns
    resolver = BoundedResolver()
    probe = ReadinessProbe(HEAD, postgres_fetch("postgresql://carvis:pw@db.stalled.invalid:5432/carvis", resolver),
                           0.2, resolver=resolver)

    async def scenario():
        baseline = threading.active_count()
        counts, reasons = [], set()
        for _ in range(6):  # sequential rounds of concurrent checks, each past the deadline
            results = await asyncio.gather(*(probe.check() for _ in range(10)))
            reasons |= {r.reason for r in results}
            counts.append(threading.active_count() - baseline)
        started = time.monotonic()
        await asyncio.to_thread(lambda: None)  # the shared executor (voice lookups) is still free
        return counts, reasons, time.monotonic() - started

    counts, reasons, executor_wait = asyncio.run(scenario())
    assert reasons == {DATABASE_UNREACHABLE}
    assert len(calls) == 1, "a new lookup must not start while one is still running"
    assert resolver.lookups_started == 1, "lookups must not queue behind a stalled one either"
    assert max(counts) <= 1, f"resolver threads accumulated: {counts}"
    assert executor_wait < 0.5
    assert probe.probes_started == 6
    release.set()
    resolver.shutdown()


def test_lookup_resumes_after_the_stalled_one_finishes(stalled_dns):
    from db.readiness import BoundedResolver, ResolverBusy

    calls, release = stalled_dns
    resolver = BoundedResolver()

    async def scenario():
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await resolver.resolve("db.stalled.invalid", "5432")
        with pytest.raises(ResolverBusy):
            await resolver.resolve("db.stalled.invalid", "5432")
        release.set()
        for _ in range(100):
            if resolver._pending.done():
                break
            await asyncio.sleep(0.01)
        return await resolver.resolve("db.stalled.invalid", "5432")

    assert asyncio.run(scenario()) == ["127.0.0.1"]
    assert len(calls) == 2
    resolver.shutdown()


class _FakeResolver:
    def __init__(self, table):
        self.table = table

    async def resolve(self, host, port):
        if host not in self.table:
            raise OSError("not found")
        return list(self.table[host])


def _attempts(conninfo, table):
    from psycopg.conninfo import conninfo_to_dict

    from db.readiness import connection_attempts

    return [conninfo_to_dict(a) for a in asyncio.run(connection_attempts(conninfo, _FakeResolver(table)))]


@pytest.mark.parametrize("conninfo,table,expected", [
    ("postgresql://u:p@db.example.test:5433/carvis", {"db.example.test": ["192.0.2.10"]},
     [("db.example.test", "192.0.2.10", "5433")]),
    ("postgresql://u:p@db.example.test/carvis", {"db.example.test": ["2001:db8::10"]},
     [("db.example.test", "2001:db8::10", "5432")]),
    ("postgresql://u:p@db.example.test/carvis", {"db.example.test": ["2001:db8::10", "192.0.2.10"]},
     [("db.example.test", "2001:db8::10", "5432"), ("db.example.test", "192.0.2.10", "5432")]),
    ("postgresql://u:p@192.0.2.20/carvis", {}, [("192.0.2.20", "192.0.2.20", "5432")]),
    ("postgresql://u:p@[2001:db8::20]:6000/carvis", {}, [("2001:db8::20", "2001:db8::20", "6000")]),
    ("postgresql://u:p@a.test:1,b.test:2/carvis", {"a.test": ["192.0.2.1"], "b.test": ["192.0.2.2", "192.0.2.3"]},
     [("a.test", "192.0.2.1", "1"), ("b.test", "192.0.2.2", "2"), ("b.test", "192.0.2.3", "2")]),
    ("postgresql://u:p@gone.test,b.test/carvis", {"b.test": ["192.0.2.2"]}, [("b.test", "192.0.2.2", "5432")]),
    ("postgresql://u:p@%2Fvar%2Frun%2Fpostgresql/carvis", {}, [("/var/run/postgresql", None, "5432")]),
])
def test_every_resolved_address_becomes_an_attempt_keeping_the_host(conninfo, table, expected):
    """IPv4, IPv6, mixed and multi-host; host stays for TLS verification; psycopg never resolves."""
    got = [(a["host"], a.get("hostaddr"), a["port"]) for a in _attempts(conninfo, table)]
    assert got == expected
    for attempt in _attempts(conninfo, table):
        assert attempt["dbname"] == "carvis" and attempt["user"] == "u"


def test_caller_hostaddr_is_used_as_given():
    from db.readiness import connection_attempts

    conninfo = "postgresql://u:p@db.example.test/carvis?hostaddr=192.0.2.40"
    assert asyncio.run(connection_attempts(conninfo, _FakeResolver({}))) == [conninfo]


def test_no_resolvable_host_is_unreachable():
    from db.readiness import NoAddress, connection_attempts

    with pytest.raises(NoAddress):
        asyncio.run(connection_attempts("postgresql://u:p@gone.test/carvis", _FakeResolver({})))


class _FakeCursor:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql):
        pass

    async def fetchall(self):
        return [(HEAD,)]


class _FakeConnection:
    closed = 0

    def cursor(self):
        return _FakeCursor()

    async def rollback(self):
        pass

    async def close(self):
        _FakeConnection.closed += 1


@pytest.fixture
def scripted_connect(monkeypatch):
    """psycopg connect scripted per hostaddr: 'refuse', 'hang' or 'ok'; records the order tried."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    behaviour, tried = {}, []

    async def connect(conninfo, **kwargs):
        address = conninfo_to_dict(conninfo).get("hostaddr")
        tried.append(address)
        action = behaviour[address]
        if action == "refuse":
            raise psycopg.OperationalError("connection refused")
        if action == "hang":
            await asyncio.sleep(3600)
        return _FakeConnection()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", staticmethod(connect))
    return behaviour, tried


def _probe_with(table, budget=2.0):
    from db.readiness import BoundedResolver

    resolver = BoundedResolver()

    class Resolver(_FakeResolver):
        def shutdown(self):
            pass

    fetch = postgres_fetch("postgresql://u:p@db.example.test/carvis", Resolver(table), budget)
    return ReadinessProbe(HEAD, fetch, budget)


@pytest.mark.parametrize("first", ["refuse", "hang"])
def test_first_address_failure_then_success(scripted_connect, first):
    behaviour, tried = scripted_connect
    behaviour.update({"2001:db8::1": first, "192.0.2.1": "ok"})
    probe = _probe_with({"db.example.test": ["2001:db8::1", "192.0.2.1"]})
    started = time.monotonic()
    result = asyncio.run(probe.check())
    assert result.reason == READY
    assert tried == ["2001:db8::1", "192.0.2.1"]
    assert time.monotonic() - started < 2.0


def test_hanging_addresses_share_one_deadline(scripted_connect):
    behaviour, tried = scripted_connect
    behaviour.update({"192.0.2.1": "hang", "192.0.2.2": "hang", "192.0.2.3": "ok"})
    probe = _probe_with({"db.example.test": ["192.0.2.1", "192.0.2.2", "192.0.2.3"]})
    started = time.monotonic()
    assert asyncio.run(probe.check()).reason == READY
    assert tried == ["192.0.2.1", "192.0.2.2", "192.0.2.3"]
    assert time.monotonic() - started < 2.0


def test_all_addresses_failing_is_unreachable_within_the_deadline(scripted_connect):
    behaviour, tried = scripted_connect
    behaviour.update({"192.0.2.1": "hang", "2001:db8::1": "refuse", "192.0.2.2": "hang"})
    probe = _probe_with({"db.example.test": ["192.0.2.1", "2001:db8::1", "192.0.2.2"]})

    async def scenario():
        started = time.monotonic()
        result = await probe.check()
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        return result, time.monotonic() - started, pending

    result, elapsed, pending = asyncio.run(scenario())
    assert result.reason == DATABASE_UNREACHABLE
    assert elapsed < 2.3 and not pending
    assert tried == ["192.0.2.1", "2001:db8::1", "192.0.2.2"]


def test_repeated_failing_probes_leave_no_background_work(scripted_connect):
    behaviour, _ = scripted_connect
    behaviour.update({"192.0.2.1": "hang"})
    probe = _probe_with({"db.example.test": ["192.0.2.1"]}, budget=0.2)

    async def scenario():
        baseline = threading.active_count()
        for _ in range(5):
            assert (await probe.check()).reason == DATABASE_UNREACHABLE
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        return pending, threading.active_count() - baseline

    pending, extra_threads = asyncio.run(scenario())
    assert not pending and extra_threads <= 0
    assert probe.probes_started == 5


# --- Multi-host ordering (round-3 review F1: a later host's DNS must not hide an earlier host) -----

class _OrderedResolver(_FakeResolver):
    """Appends ``resolve:<host>`` to the shared order list; names in ``stall`` never answer."""

    def __init__(self, table, order, stall=(), busy=()):
        super().__init__(table)
        self.order, self.stall, self.busy = order, set(stall), set(busy)

    async def resolve(self, host, port):
        from db.readiness import ResolverBusy

        self.order.append(f"resolve:{host}")
        if host in self.busy:
            raise ResolverBusy()
        if host in self.stall:
            await asyncio.sleep(3600)
        return await super().resolve(host, port)


def _multi_host_probe(url, resolver, budget=2.0):
    return ReadinessProbe(HEAD, postgres_fetch(url, resolver, budget), budget)


def test_stalled_later_host_dns_does_not_hide_a_reachable_first_host(scripted_connect):
    behaviour, order = scripted_connect
    behaviour.update({"192.0.2.1": "ok"})
    resolver = _OrderedResolver({"a.test": ["192.0.2.1"]}, order, stall={"b.test"})
    probe = _multi_host_probe("postgresql://u:p@a.test,b.test/carvis", resolver, budget=0.5)
    assert asyncio.run(probe.check()).reason == READY
    assert order == ["resolve:a.test", "192.0.2.1"], "a later host must not be resolved before an earlier one is tried"


def test_stalled_later_host_never_reaches_the_real_resolver_thread(scripted_connect, stalled_dns):
    """Same case through BoundedResolver and the real getaddrinfo: the stalled name is never looked up."""
    from db.readiness import BoundedResolver

    behaviour, tried = scripted_connect
    behaviour.update({"127.0.0.1": "ok", "::1": "ok"})
    calls, release = stalled_dns
    resolver = BoundedResolver()
    probe = _multi_host_probe("postgresql://u:p@localhost,db.stalled.invalid/carvis", resolver, budget=0.5)
    try:
        assert asyncio.run(probe.check()).reason == READY
        assert calls == [] and resolver.lookups_started == 1
        assert len(tried) == 1
    finally:
        release.set()
        resolver.shutdown()


def test_next_host_is_resolved_only_after_every_address_of_the_previous_one_fails(scripted_connect):
    behaviour, order = scripted_connect
    behaviour.update({"2001:db8::1": "refuse", "192.0.2.1": "refuse", "192.0.2.2": "ok"})
    resolver = _OrderedResolver({"a.test": ["2001:db8::1", "192.0.2.1"], "b.test": ["192.0.2.2"]}, order)
    assert asyncio.run(_multi_host_probe("postgresql://u:p@a.test,b.test/carvis", resolver).check()).reason == READY
    assert order == ["resolve:a.test", "2001:db8::1", "192.0.2.1", "resolve:b.test", "192.0.2.2"]


def test_stalled_connection_to_first_host_leaves_time_for_a_later_host(scripted_connect):
    """A stalled connection attempt (not a stalled lookup): later, still unresolved hosts count in the share."""
    behaviour, order = scripted_connect
    behaviour.update({"192.0.2.1": "hang", "192.0.2.2": "ok"})
    resolver = _OrderedResolver({"a.test": ["192.0.2.1"], "b.test": ["192.0.2.2"]}, order)
    started = time.monotonic()
    assert asyncio.run(_multi_host_probe("postgresql://u:p@a.test,b.test/carvis", resolver).check()).reason == READY
    assert order == ["resolve:a.test", "192.0.2.1", "resolve:b.test", "192.0.2.2"]
    assert time.monotonic() - started < 2.0


def test_random_load_balancing_shuffles_hosts_before_resolving_them(scripted_connect, monkeypatch):
    import random

    monkeypatch.setattr(random, "shuffle", lambda items: items.reverse())
    behaviour, order = scripted_connect
    behaviour.update({"192.0.2.2": "ok"})
    resolver = _OrderedResolver({"a.test": ["192.0.2.1"], "b.test": ["192.0.2.2"]}, order, stall={"a.test"})
    probe = _multi_host_probe("postgresql://u:p@a.test,b.test/carvis?load_balance_hosts=random", resolver, 0.5)
    assert asyncio.run(probe.check()).reason == READY
    assert order == ["resolve:b.test", "192.0.2.2"]


def test_busy_resolver_skips_that_host_and_tries_the_next(scripted_connect):
    """A lookup still hung from an earlier probe makes that host unresolvable, as libpq skips such hosts."""
    behaviour, order = scripted_connect
    behaviour.update({"192.0.2.1": "refuse", "192.0.2.3": "ok"})
    resolver = _OrderedResolver({"a.test": ["192.0.2.1"]}, order, busy={"b.test"})
    probe = _multi_host_probe("postgresql://u:p@a.test,b.test,192.0.2.3/carvis", resolver)
    assert asyncio.run(probe.check()).reason == READY
    assert order == ["resolve:a.test", "192.0.2.1", "resolve:b.test", "192.0.2.3"]
