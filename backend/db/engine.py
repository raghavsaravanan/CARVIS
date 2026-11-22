"""Engine and session factory (M2 Track B1).

The engine is created lazily at startup only when ``CARVIS_DATABASE_URL`` is configured; creating it
never opens a connection. No request route uses it in B1; B2 adds the request-path unit of work.
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
