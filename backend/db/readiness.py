"""Bounded, single-flight readiness probe for ``/readyz`` (M2 Track B1).

Ready means: PostgreSQL is reachable and the Alembic version recorded in
``carvis_migrations.alembic_version`` is the head this build ships. Anything else is not ready.

Bounds:

- Connection establishment (including TLS) and the query run on the event loop through psycopg 3's
  ``AsyncConnection``. One ``asyncio.timeout`` covers the whole probe; when it expires the coroutine
  is cancelled and the connection closed.
- Host names are resolved by :class:`BoundedResolver`, never by psycopg: a blocking
  ``getaddrinfo`` cannot be cancelled, so it runs on one dedicated thread owned by the probe (never
  the shared default executor that the voice path's lookups use), and while a lookup is still
  running no new one starts or queues and the probe answers ``database_unreachable`` at once.
  Every resolved address (IPv6 and IPv4) becomes its own connection attempt with ``hostaddr`` set
  (``host`` is kept for TLS verification), so psycopg does not resolve again, and an unreachable
  first address falls back to the next within the same deadline. At most one resolver thread
  exists, whatever the outage length; a lookup hung at shutdown can delay process exit until the
  system resolver returns.
- Each probe opens one fresh connection and closes it, so there is no pool checkout to exhaust.
- At most one probe runs at a time. Concurrent ``/readyz`` requests share it, so an outage cannot
  multiply connections or tasks, whatever the request rate.
- Server-side ``statement_timeout`` and ``lock_timeout`` are set with ``SET LOCAL`` (transaction
  scoped, so safe through any pooler), and prepared statements are disabled.

Outcomes are fixed codes. Exception messages, which can name hosts or users, are never logged or
returned; only the exception type name is logged.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Awaitable, Callable

from db.roles import METADATA_SCHEMA, VERSION_TABLE
from log_config import log_event, register_values
from settings import Settings

READY = "ready"
STARTING = "starting"
DATABASE_UNCONFIGURED = "database_unconfigured"
DATABASE_MISCONFIGURED = "database_misconfigured"
DATABASE_UNREACHABLE = "database_unreachable"
MIGRATIONS_PENDING = "migrations_pending"
OUTCOMES = (READY, STARTING, DATABASE_UNCONFIGURED, DATABASE_MISCONFIGURED, DATABASE_UNREACHABLE,
            MIGRATIONS_PENDING)

STATEMENT_TIMEOUT_MS = 1500
LOCK_TIMEOUT_MS = 500
CONNECT_TIMEOUT_SECONDS = 2
READINESS_BUDGET_SECONDS = 2.0
QUERY_RESERVE_SECONDS = 0.25
VERSION_QUERY = f"SELECT version_num FROM {METADATA_SCHEMA}.{VERSION_TABLE}"
# Missing schema or table: nothing has been migrated yet.
_NOT_MIGRATED_SQLSTATES = frozenset({"3F000", "42P01"})

logger = logging.getLogger("carvis.readiness")
register_values("component", ["readiness"])

Fetch = Callable[[], Awaitable[list[str]]]
"""Returns the recorded Alembic revisions."""


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reason: str


def expected_head() -> str:
    """The single head of the shipped Alembic chain (raises if the chain is not linear)."""
    from db.history import check_linear_history, script_directory

    return check_linear_history(script_directory())


class ResolverBusy(RuntimeError):
    """A previous host-name lookup is still running; no new one is started."""


class BoundedResolver:
    """Host-name lookups on one dedicated thread, never more than one outstanding.

    ``asyncio.wrap_future`` lets a caller stop waiting, but the lookup itself keeps running until the
    system resolver returns; :attr:`_pending` tracks that real completion, not the waiter's.
    """

    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._pending: Future | None = None
        self.lookups_started = 0

    async def resolve(self, host: str, port: str) -> list[str]:
        """Every address ``host`` resolves to, in resolver order, without duplicates."""
        if self._pending is not None and not self._pending.done():
            raise ResolverBusy()
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="carvis-readiness-dns")
        self.lookups_started += 1
        self._pending = self._executor.submit(socket.getaddrinfo, host, port, proto=socket.IPPROTO_TCP,
                                              type=socket.SOCK_STREAM)
        answers = await asyncio.wrap_future(self._pending)
        return list(dict.fromkeys(str(answer[4][0]) for answer in answers))

    def shutdown(self) -> None:
        if self._executor is not None:
            # The lifespan never waits for a hung lookup. Its one thread still ends only when the
            # system resolver returns, and the interpreter joins it at exit, so a lookup hung at
            # shutdown can delay process exit by up to the resolver's own timeout.
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class NoAddress(RuntimeError):
    """No configured host resolved to an address."""


async def connection_attempts(conninfo: str, resolver: BoundedResolver) -> list[str]:
    """One single-address connection string per resolved address, in the order libpq would try them.

    Mirrors libpq and psycopg: ``host`` (or ``PGHOST``) may list several hosts with matching ports;
    socket paths and IP literals need no lookup; a host name yields one attempt per address it
    resolves to (IPv6 and IPv4 alike); a host that fails to resolve is skipped;
    ``load_balance_hosts=random`` shuffles the attempts. Each attempt keeps ``host`` (TLS
    verification) and sets ``hostaddr``, so psycopg never resolves names itself. A caller-supplied
    ``hostaddr`` is used as given.
    """
    import random

    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(conninfo)
    if params.get("hostaddr"):
        return [conninfo]
    hosts_value = str(params.get("host") or os.getenv("PGHOST") or "")
    if not hosts_value:
        return [conninfo]
    hosts = hosts_value.split(",")
    ports = str(params.get("port") or os.getenv("PGPORT") or "5432").split(",")
    entries: list[tuple[str, str | None, str]] = []
    for index, host in enumerate(hosts):
        port = (ports[index] if len(ports) == len(hosts) else ports[0]) or "5432"
        if not host or host.startswith("/") or host[1:2] == ":":
            entries.append((host, None, port))  # Unix socket or libpq default: nothing to resolve
        elif _is_ip(host):
            entries.append((host, host, port))
        else:
            try:
                addresses = await resolver.resolve(host, port)
            except OSError:
                continue  # as psycopg does: try the remaining hosts
            entries.extend((host, address, port) for address in addresses)
    if not entries:
        raise NoAddress()
    if str(params.get("load_balance_hosts") or "") == "random":
        random.shuffle(entries)
    attempts = []
    for host, address, port in entries:
        overrides = {"host": host, "port": port}
        if address is not None:
            overrides["hostaddr"] = address
        attempts.append(make_conninfo(conninfo, **overrides))
    return attempts


def postgres_fetch(conninfo: str, resolver: BoundedResolver | None = None,
                   budget_seconds: float = READINESS_BUDGET_SECONDS) -> Fetch:
    """A fetch that connects to the first reachable address, reads the version table and closes.

    The probe's single deadline covers everything; within it, each remaining address gets a fair
    share of the time left (less a reserve for the query), so an address that silently drops
    packets cannot consume the whole deadline before a later, reachable one is tried.
    """
    resolver = resolver or BoundedResolver()

    async def fetch() -> list[str]:
        import psycopg

        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget_seconds
        attempts = await connection_attempts(conninfo, resolver)
        last_error: BaseException | None = None
        for index, target in enumerate(attempts):
            remaining = deadline - loop.time() - QUERY_RESERVE_SECONDS
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining / (len(attempts) - index)):
                    connection = await psycopg.AsyncConnection.connect(
                        target, connect_timeout=CONNECT_TIMEOUT_SECONDS, prepare_threshold=None, autocommit=False)
            except (OSError, psycopg.OperationalError, TimeoutError) as exc:
                last_error = exc
                continue
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                    await cursor.execute(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}")
                    await cursor.execute(VERSION_QUERY)
                    rows = await cursor.fetchall()
                await connection.rollback()
                return [row[0] for row in rows]
            finally:
                await connection.close()
        raise last_error if last_error is not None else TimeoutError()

    return fetch


def _sqlstate(exc: BaseException) -> str | None:
    return getattr(exc, "sqlstate", None)


class ReadinessProbe:
    """Single-flight readiness check with a hard total deadline."""

    def __init__(self, head: str, fetch: Fetch | None, timeout_seconds: float,
                 unavailable_reason: str | None = None, resolver: BoundedResolver | None = None) -> None:
        self._head = head
        self._fetch = fetch
        self._resolver = resolver
        self._timeout = timeout_seconds
        self._unavailable_reason = unavailable_reason
        self._inflight: asyncio.Task[Readiness] | None = None
        self.probes_started = 0

    @classmethod
    def from_settings(cls, settings: Settings, head: str) -> "ReadinessProbe":
        if settings.database_status == "invalid":
            return cls(head, None, settings.readiness_timeout_seconds, DATABASE_MISCONFIGURED)
        if not settings.database_ready_to_probe:
            return cls(head, None, settings.readiness_timeout_seconds, DATABASE_UNCONFIGURED)
        from db.engine import libpq_conninfo

        assert settings.database_url is not None
        resolver = BoundedResolver()
        return cls(head, postgres_fetch(libpq_conninfo(settings.database_url), resolver,
                                        settings.readiness_timeout_seconds),
                   settings.readiness_timeout_seconds, resolver=resolver)

    async def _probe(self) -> Readiness:
        assert self._fetch is not None
        self.probes_started += 1
        try:
            async with asyncio.timeout(self._timeout):
                revisions = await self._fetch()
        except TimeoutError:
            log_event(logger, logging.WARNING, "readiness probe timed out", component="readiness",
                      outcome=DATABASE_UNREACHABLE)
            return Readiness(False, DATABASE_UNREACHABLE)
        except Exception as exc:  # noqa: BLE001 - any failure is "not ready"; only its type is logged
            if _sqlstate(exc) in _NOT_MIGRATED_SQLSTATES:
                return Readiness(False, MIGRATIONS_PENDING)
            log_event(logger, logging.WARNING, "readiness probe failed", component="readiness",
                      outcome=DATABASE_UNREACHABLE, error=type(exc).__name__)
            return Readiness(False, DATABASE_UNREACHABLE)
        if revisions != [self._head]:
            return Readiness(False, MIGRATIONS_PENDING)
        return Readiness(True, READY)

    async def check(self) -> Readiness:
        if self._unavailable_reason is not None:
            return Readiness(False, self._unavailable_reason)
        task = self._inflight
        if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
            task = asyncio.get_running_loop().create_task(self._probe())
            self._inflight = task
        # shield: one waiter's cancellation (a client disconnecting) must not cancel the shared probe.
        return await asyncio.shield(task)

    async def close(self) -> None:
        if self._resolver is not None:
            self._resolver.shutdown()
        task, self._inflight = self._inflight, None
        if task is not None and not task.done() and task.get_loop() is asyncio.get_running_loop():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - shutting down
                pass
