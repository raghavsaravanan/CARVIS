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
  Hosts are resolved lazily, in libpq's order: a host is looked up only after every address of the
  hosts before it has failed, so a stalled lookup of a later host never delays a reachable earlier
  one. Every resolved address (IPv6 and IPv4) becomes its own connection attempt with ``hostaddr``
  set (``host`` is kept for TLS verification), so psycopg does not resolve again, and an
  unreachable address falls back to the next within the same deadline. At most one resolver
  thread exists, whatever the outage length; a lookup hung at shutdown can delay process exit
  until the system resolver returns. Accepted B1 limit: a stalled lookup of the *first* host name
  holds the one thread, so the probe answers ``database_unreachable`` at the deadline even if a
  later host is healthy (libpq would block on that lookup too).
- Each probe opens one fresh connection and closes it, so there is no pool checkout to exhaust.
- At most one probe runs at a time. Concurrent ``/readyz`` requests share it, so an outage cannot
  multiply connections or tasks, whatever the request rate.
- Server-side ``statement_timeout`` and ``lock_timeout`` are set with ``SET LOCAL`` (transaction
  scoped, so safe through any pooler), and prepared statements are disabled.

Role switch and runtime-login self-check (M2 B2a; doc 04 "Roles"):

- The runtime login holds no privileges of its own, so the probe runs ``SET LOCAL ROLE carvis_app``
  before reading the version table. A missing role means nothing is migrated yet
  (``migrations_pending``); a login that may not switch is ``database_misconfigured``.
- With ``enforce_login`` (every environment except local), the probe first validates
  ``session_user`` with the same query as ``python -m db.runtime_login check``: a superuser,
  ``BYPASSRLS``, object-owning or otherwise unsafe login is ``database_misconfigured``.
- Connection settings that break the explicit-connection rules (:mod:`db.conninfo`: service files,
  host, ``hostaddr`` and port counts) are ``database_misconfigured`` instead of being tried with a
  guessed port. Every libpq parameter the probe interprets also honors its environment variable.

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
from typing import AsyncIterator, Awaitable, Callable

from db.conninfo import ConnectionConfigError, host_port_entries, libpq_setting, reject_service_files
from db.roles import APP_ROLE, METADATA_SCHEMA, VERSION_TABLE
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
# SET ROLE to a role that does not exist (checked at that step only: 22023 is a generic code).
_ROLE_MISSING_SQLSTATE = "22023"
# The login may not SET ROLE carvis_app: a deployment (not a migration) problem.
_MISCONFIGURED_SQLSTATES = frozenset({"42501"})

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


class UnsafeLogin(RuntimeError):
    """The connected login fails the runtime-login check. Carries condition names only."""


class RuntimeRoleMissing(RuntimeError):
    """``carvis_app`` does not exist yet: the runtime roles are not migrated."""


async def host_attempts(conninfo: str, resolver: BoundedResolver) -> AsyncIterator[tuple[list[str], int]]:
    """Each host's single-address connection strings, in the order libpq would try them, resolved lazily.

    Yields ``(attempts, later_hosts)`` one host at a time; the next host is resolved only when the
    caller asks for it, after every attempt for the previous host has failed. ``later_hosts`` is the
    number of hosts not yet yielded.

    Mirrors libpq and psycopg: ``host`` (or ``PGHOST``) may list several hosts with matching ports;
    socket paths and IP literals need no lookup; a host name yields one attempt per address it
    resolves to (IPv6 and IPv4 alike); a host that fails to resolve, or cannot be resolved because an
    earlier lookup is still running, is skipped; ``load_balance_hosts=random`` shuffles the hosts,
    then each host's addresses. Each attempt keeps ``host`` (TLS verification) and sets ``hostaddr``,
    so psycopg never resolves names itself. A caller-supplied ``hostaddr`` is used as given.
    Raises :class:`NoAddress` if no host yields an attempt.
    """
    import random

    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(conninfo)
    # B2a (N2/N3): never guess a port or let libpq read a service file the resolver cannot see.
    reject_service_files(params)
    entries = host_port_entries(params)
    hosts_value = libpq_setting(params, "host")
    # Explicit addresses (parameter or PGHOSTADDR) need no lookup: libpq connects to them itself and
    # keeps the host names for TLS, so the connection string is passed through unchanged.
    if libpq_setting(params, "hostaddr") or not hosts_value:
        yield [conninfo], 0
        return
    shuffle = libpq_setting(params, "load_balance_hosts") == "random"
    if shuffle:
        random.shuffle(entries)
    yielded = False
    for index, (host, port) in enumerate(entries):
        if not host or host.startswith("/") or host[1:2] == ":":
            addresses: list[str | None] = [None]  # Unix socket or libpq default: nothing to resolve
        elif _is_ip(host):
            addresses = [host]
        else:
            try:
                addresses = list(await resolver.resolve(host, port))
            except (OSError, ResolverBusy):
                continue  # as psycopg does: try the remaining hosts
            if shuffle:
                random.shuffle(addresses)
        attempts = []
        for address in addresses:
            overrides = {"host": host, "port": port}
            if address is not None:
                overrides["hostaddr"] = address
            attempts.append(make_conninfo(conninfo, **overrides))
        if attempts:
            yielded = True
            yield attempts, len(entries) - index - 1
    if not yielded:
        raise NoAddress()


async def connection_attempts(conninfo: str, resolver: BoundedResolver) -> list[str]:
    """Every attempt :func:`host_attempts` yields, resolving all hosts (inspection and tests only).

    The probe itself never calls this: it consumes :func:`host_attempts` lazily.
    """
    return [attempt async for attempts, _ in host_attempts(conninfo, resolver) for attempt in attempts]


async def open_connection(conninfo: str, resolver: BoundedResolver, deadline: float,
                          reserve_seconds: float = QUERY_RESERVE_SECONDS):
    """Connect to the first reachable address before ``deadline`` (``loop.time()`` units).

    Host names are resolved lazily by ``resolver`` in libpq order (:func:`host_attempts`); each
    attempt gets a fair share of the time left (less ``reserve_seconds``), counting the remaining
    addresses of the current host plus one per host not yet resolved, so an address that silently
    drops packets cannot consume the whole deadline before a later, reachable one is tried. Shared by
    the readiness probe and the request-path engine (:func:`db.engine.create_async_app_engine`).
    Raises the last connection error, or ``TimeoutError``.
    """
    import psycopg

    loop = asyncio.get_running_loop()
    last_error: BaseException | None = None
    hosts = host_attempts(conninfo, resolver)
    try:
        # The deadline covers host-name resolution too, not only each connect attempt (B2a: a stalled
        # lookup must not outlive the caller's deadline on the request path).
        async with asyncio.timeout_at(deadline):
            async for attempts, later_hosts in hosts:
                for index, target in enumerate(attempts):
                    remaining = deadline - loop.time() - reserve_seconds
                    if remaining <= 0:
                        raise last_error if last_error is not None else TimeoutError()
                    share = remaining / (len(attempts) - index + later_hosts)
                    try:
                        async with asyncio.timeout(share):
                            return await psycopg.AsyncConnection.connect(
                                target, connect_timeout=CONNECT_TIMEOUT_SECONDS, prepare_threshold=None,
                                autocommit=False)
                    except (OSError, psycopg.OperationalError, TimeoutError) as exc:
                        last_error = exc
                        continue
    finally:
        await hosts.aclose()
    raise last_error if last_error is not None else TimeoutError()


def postgres_fetch(conninfo: str, resolver: BoundedResolver | None = None,
                   budget_seconds: float = READINESS_BUDGET_SECONDS, *, enforce_login: bool = True) -> Fetch:
    """A fetch that connects to the first reachable address, reads the version table and closes.

    The probe's single deadline covers everything, host-name lookups included (see
    :func:`open_connection`). With ``enforce_login`` the connected login must pass the runtime-login
    check; the version table is read as ``carvis_app`` (``SET LOCAL ROLE``).
    """
    resolver = resolver or BoundedResolver()

    async def fetch() -> list[str]:
        loop = asyncio.get_running_loop()
        connection = await open_connection(conninfo, resolver, loop.time() + budget_seconds)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                await cursor.execute(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}")
                if enforce_login:
                    await _check_login(cursor)
                try:
                    await cursor.execute(f"SET LOCAL ROLE {APP_ROLE}")
                except Exception as exc:  # noqa: BLE001 - classified by SQLSTATE only
                    if _sqlstate(exc) == _ROLE_MISSING_SQLSTATE:
                        raise RuntimeRoleMissing() from None
                    raise
                await cursor.execute(VERSION_QUERY)
                rows = await cursor.fetchall()
            await connection.rollback()
            return [row[0] for row in rows]
        finally:
            await connection.close()

    return fetch


async def _check_login(cursor) -> None:
    """Runtime roles first (absent ⇒ not migrated yet), then the runtime-login conditions."""
    from db.runtime_login import LOGIN_CHECK_SQL, RUNTIME_MEMBERSHIPS, check_params

    await cursor.execute("SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
                         (list(RUNTIME_MEMBERSHIPS),))
    if (await cursor.fetchone())[0] != len(RUNTIME_MEMBERSHIPS):
        raise RuntimeRoleMissing()
    await cursor.execute("SELECT session_user")
    login = (await cursor.fetchone())[0]
    await cursor.execute(LOGIN_CHECK_SQL, check_params(login))
    found = sorted({row[0] for row in await cursor.fetchall()})
    if found:
        raise UnsafeLogin(", ".join(found))


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
        from webhook_auth import LOCAL

        assert settings.database_url is not None
        resolver = BoundedResolver()
        # Local development may use a superuser; every other environment needs a safe runtime login.
        return cls(head, postgres_fetch(libpq_conninfo(settings.database_url), resolver,
                                        settings.readiness_timeout_seconds,
                                        enforce_login=settings.environment != LOCAL),
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
        except (ConnectionConfigError, UnsafeLogin) as exc:
            log_event(logger, logging.WARNING, "readiness probe misconfigured", component="readiness",
                      outcome=DATABASE_MISCONFIGURED, error=type(exc).__name__)
            return Readiness(False, DATABASE_MISCONFIGURED)
        except RuntimeRoleMissing:
            return Readiness(False, MIGRATIONS_PENDING)
        except Exception as exc:  # noqa: BLE001 - any failure is "not ready"; only its type is logged
            if _sqlstate(exc) in _NOT_MIGRATED_SQLSTATES:
                return Readiness(False, MIGRATIONS_PENDING)
            if _sqlstate(exc) in _MISCONFIGURED_SQLSTATES:
                log_event(logger, logging.WARNING, "readiness probe misconfigured", component="readiness",
                          outcome=DATABASE_MISCONFIGURED, error=type(exc).__name__)
                return Readiness(False, DATABASE_MISCONFIGURED)
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
