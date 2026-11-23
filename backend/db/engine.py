"""Engine and session factory (M2 Track B1).

The engine is created lazily at startup only when ``CARVIS_DATABASE_URL`` is configured; creating it
never opens a connection. No request route uses it in B1; B2 adds the request-path unit of work.
M2 B2a adds the bounded async request-path engine (:func:`create_async_app_engine`, below), not yet
wired to any route or to the lifespan.
Settings follow ``docs/architecture/04-identity-tenancy-rls.md`` ("Pooling"): pre-ping, rollback on
return, and psycopg prepared statements disabled (``prepare_threshold=None``), which works on any
server and behind any pooler mode. ``hide_parameters`` keeps bound values out of SQLAlchemy errors.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from settings import DatabaseUrl

APP_POOL_SIZE = 5
APP_MAX_OVERFLOW = 2
APP_POOL_TIMEOUT_SECONDS = 5
CONNECT_TIMEOUT_SECONDS = 2


def create_app_engine(url: DatabaseUrl) -> Engine:
    return create_engine(
        url.reveal(),
        pool_size=APP_POOL_SIZE,
        max_overflow=APP_MAX_OVERFLOW,
        pool_timeout=APP_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
        pool_reset_on_return="rollback",
        hide_parameters=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS, "prepare_threshold": None},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """One unit of work per session; no autocommit sessions (doc 04, "Pooling")."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def libpq_conninfo(url: DatabaseUrl) -> str:
    """The URL as a plain libpq ``postgresql://`` connection string for psycopg."""
    return make_url(url.reveal()).set(drivername="postgresql").render_as_string(hide_password=False)


# --- Request-path async engine (M2 B2a) ----------------------------------------------------------
#
# Bounded connection creation for the request path (doc 04 "Pooling"). Connections are opened by
# :func:`db.readiness.open_connection`: host names are resolved by :class:`SharedResolver` on its own
# small thread pool (never the shared default executor that the voice path's lookups use), each
# attempt sets ``hostaddr`` and keeps ``host`` for TLS, and one deadline covers resolution and
# connect. No route or lifespan uses this engine in B2a; B2b wires it with the session context.

ASYNC_CONNECT_DEADLINE_SECONDS = 2.0
RESOLVER_THREADS = 2
RESOLVER_CACHE_SECONDS = 30.0


class SharedResolver:
    """Host-name lookups for the request path: concurrent lookups of one name share one in-flight
    lookup, successful answers are cached briefly, and the dedicated pool is bounded.

    Unlike readiness's single-flight :class:`db.readiness.BoundedResolver`, concurrent pool fills
    (several requests on a cold pool) all wait on the same lookup instead of failing. Each waiter is
    bounded by its own caller's deadline; a waiter that gives up never cancels the shared lookup.
    At most ``threads`` lookups run at once; a lookup for a new name beyond that raises
    :class:`db.readiness.ResolverBusy`, so a stalled resolver cannot accumulate threads.
    """

    def __init__(self, threads: int = RESOLVER_THREADS, cache_seconds: float = RESOLVER_CACHE_SECONDS,
                 clock=None) -> None:
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor

        self._executor = ThreadPoolExecutor(max_workers=threads, thread_name_prefix="carvis-db-dns")
        self._threads = threads
        self._cache_seconds = cache_seconds
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._inflight: dict = {}
        self._cache: dict = {}
        self.lookups_started = 0

    async def resolve(self, host: str, port: str) -> list[str]:
        import asyncio
        import socket

        from db.readiness import ResolverBusy

        key = (host, port)
        cached = self._cache.get(key)
        if cached is not None and cached[0] > self._clock():
            return list(cached[1])
        with self._lock:
            future = self._inflight.get(key)
            if future is None or future.done():
                running = sum(1 for pending in self._inflight.values() if not pending.done())
                if running >= self._threads:
                    raise ResolverBusy()
                self.lookups_started += 1
                future = self._executor.submit(socket.getaddrinfo, host, port, proto=socket.IPPROTO_TCP,
                                               type=socket.SOCK_STREAM)
                self._inflight[key] = future
        # shield: a waiter cancelled by its deadline must not cancel the lookup other waiters share.
        answers = await asyncio.shield(asyncio.wrap_future(future))
        addresses = list(dict.fromkeys(str(answer[4][0]) for answer in answers))
        self._cache[key] = (self._clock() + self._cache_seconds, addresses)
        return list(addresses)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def create_async_app_engine(url: DatabaseUrl, resolver: SharedResolver | None = None,
                            connect_deadline_seconds: float = ASYNC_CONNECT_DEADLINE_SECONDS):
    """The request-path ``AsyncEngine`` and its resolver (shut the resolver down after disposing)."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from db.readiness import open_connection

    resolver = resolver or SharedResolver()
    conninfo = libpq_conninfo(url)

    async def creator():
        loop = asyncio.get_running_loop()
        return await open_connection(conninfo, resolver, loop.time() + connect_deadline_seconds,
                                     reserve_seconds=0.0)

    engine = create_async_engine(
        "postgresql+psycopg://",
        async_creator=creator,
        pool_size=APP_POOL_SIZE,
        max_overflow=APP_MAX_OVERFLOW,
        pool_timeout=APP_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
        pool_reset_on_return="rollback",
        hide_parameters=True,
    )
    return engine, resolver
