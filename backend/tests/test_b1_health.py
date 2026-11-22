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

    assert asyncio.run(scenario()) == "127.0.0.1"
    assert len(calls) == 2
    resolver.shutdown()


@pytest.mark.parametrize("conninfo,expected_hostaddr", [
    ("postgresql://u:p@db.example.test:5433/carvis", "192.0.2.10"),
    ("postgresql://u:p@192.0.2.20/carvis", "192.0.2.20"),
    ("postgresql://u:p@db.example.test,192.0.2.30/carvis", "192.0.2.10,192.0.2.30"),
    ("postgresql://u:p@db.example.test/carvis?hostaddr=192.0.2.40", "192.0.2.40"),
    ("postgresql://u:p@%2Fvar%2Frun%2Fpostgresql/carvis", None),
])
def test_psycopg_receives_a_resolved_hostaddr(conninfo, expected_hostaddr):
    """psycopg resolves names itself unless hostaddr is set; the probe always sets it for names."""
    from psycopg.conninfo import conninfo_to_dict

    from db.readiness import resolved_conninfo

    class FakeResolver:
        async def resolve(self, host, port):
            assert host == "db.example.test"
            return "192.0.2.10"

    params = conninfo_to_dict(asyncio.run(resolved_conninfo(conninfo, FakeResolver())))
    assert params.get("hostaddr") == expected_hostaddr
    assert params["dbname"] == "carvis"
