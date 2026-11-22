"""Bounded, single-flight readiness probe for ``/readyz`` (M2 Track B1).

Ready means: PostgreSQL is reachable and the Alembic version recorded in
``carvis_migrations.alembic_version`` is the head this build ships. Anything else is not ready.

Bounds (no worker thread, no pool):

- The probe is a coroutine on the event loop using psycopg 3's ``AsyncConnection``, so DNS lookup,
  connection establishment (including TLS) and the query all run as awaitables. One
  ``asyncio.timeout`` covers the whole probe; when it expires the coroutine is cancelled and the
  connection closed. Nothing keeps running in the background.
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
import logging
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


def postgres_fetch(conninfo: str) -> Fetch:
    """A fetch that opens one psycopg ``AsyncConnection``, reads the version table and closes it."""

    async def fetch() -> list[str]:
        import psycopg

        connection = await psycopg.AsyncConnection.connect(
            conninfo, connect_timeout=CONNECT_TIMEOUT_SECONDS, prepare_threshold=None, autocommit=False)
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

    return fetch


def _sqlstate(exc: BaseException) -> str | None:
    return getattr(exc, "sqlstate", None)


class ReadinessProbe:
    """Single-flight readiness check with a hard total deadline."""

    def __init__(self, head: str, fetch: Fetch | None, timeout_seconds: float,
                 unavailable_reason: str | None = None) -> None:
        self._head = head
        self._fetch = fetch
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
        return cls(head, postgres_fetch(libpq_conninfo(settings.database_url)), settings.readiness_timeout_seconds)

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
        task, self._inflight = self._inflight, None
        if task is not None and not task.done() and task.get_loop() is asyncio.get_running_loop():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - shutting down
                pass
