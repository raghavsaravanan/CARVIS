"""Two-phase request session context (M2 B2b-2; doc 04 "Context carrier", ADR-0003).

Each ``/v1`` request runs two transactions on the pooled runtime login, each under one role:

1. **Bootstrap** (:func:`provision`): ``carvis_bootstrap`` calls ``carvis.ensure_principal`` for the verified
   principal, in READ COMMITTED, and commits ``(user_id, status)``.
2. **Tenant** (:func:`tenant_session`): ``carvis_app`` with ``app.user_id`` set and ``app.workspace_ids`` derived
   from the caller's memberships under row-level security, all before the caller's first query.

An ``after_begin`` listener on :class:`RequestSession` installs the context and refuses any transaction whose
session carries none (:class:`ContextMissing`), before any statement is sent. One session factory and two context
managers are the only code that sets a context. Only ``SET TRANSACTION``, ``SET LOCAL`` and
``set_config(..., true)`` are used, so nothing survives commit, rollback or the connection's return to the pool.

Every statement this module sends is one of :data:`APPROVED_STATEMENTS`, written in driver form and executed with
``exec_driver_sql`` (no SQLAlchemy compilation), with every type, function and relation schema-qualified so the
caller's ``search_path`` resolves nothing. Tests compare the SQL captured at the driver with this list exactly.

Not wired to any route yet (B2c).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Iterable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from db.roles import APP_ROLE, BOOTSTRAP_ROLE

CONTEXT_KEY = "carvis.request_context"
WORKSPACES_KEY = "carvis.workspace_ids"

# The complete set of SQL this module sends (driver form, psycopg pyformat placeholders).
SET_READ_COMMITTED = "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
SET_BOOTSTRAP_ROLE = f"SET LOCAL ROLE {BOOTSTRAP_ROLE}"
ENSURE_PRINCIPAL = ("SELECT p.user_id, p.status FROM carvis.ensure_principal(%(issuer)s, %(subject)s, %(email)s) "
                    "AS p")
SET_APP_ROLE = f"SET LOCAL ROLE {APP_ROLE}"
SET_USER_ID = "SELECT pg_catalog.set_config('app.user_id', %(user_id)s, true)"
SET_WORKSPACE_IDS = ("SELECT pg_catalog.set_config('app.workspace_ids', "
                     "COALESCE(pg_catalog.array_agg(m.workspace_id)::pg_catalog.text, '{}'), true), "
                     "pg_catalog.array_agg(m.workspace_id) FROM carvis.memberships AS m")
APPROVED_STATEMENTS = (SET_READ_COMMITTED, SET_BOOTSTRAP_ROLE, ENSURE_PRINCIPAL, SET_APP_ROLE, SET_USER_ID,
                       SET_WORKSPACE_IDS)


class ContextMissing(RuntimeError):
    """A request-path transaction began without a bootstrap or tenant context."""


class InactivePrincipal(RuntimeError):
    """A tenant transaction was requested for a user whose status is not ``active``."""


@dataclass(frozen=True)
class BootstrapContext:
    issuer: str
    subject: str
    email: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.issuer, str) or not isinstance(self.subject, str) \
                or not (self.email is None or isinstance(self.email, str)):
            raise TypeError("BootstrapContext takes strings")


@dataclass(frozen=True)
class ProvisionedUser:
    user_id: uuid.UUID
    status: str

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, uuid.UUID):
            raise TypeError("ProvisionedUser.user_id must be a uuid.UUID")


@dataclass(frozen=True)
class TenantContext:
    user_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, uuid.UUID):
            raise TypeError("TenantContext.user_id must be a uuid.UUID")


class RequestSession(Session):
    """The only session class with the context listener; other sessions are unaffected."""


def _after_begin(session: Session, transaction, connection) -> None:
    if transaction.nested:
        return  # a SAVEPOINT keeps the root transaction's context; nothing is re-derived
    context = session.info.get(CONTEXT_KEY)
    if isinstance(context, BootstrapContext):
        connection.exec_driver_sql(SET_READ_COMMITTED)  # must precede any query in the transaction
        connection.exec_driver_sql(SET_BOOTSTRAP_ROLE)
    elif isinstance(context, TenantContext):
        connection.exec_driver_sql(SET_APP_ROLE)
        connection.exec_driver_sql(SET_USER_ID, {"user_id": str(context.user_id)})
        row = connection.exec_driver_sql(SET_WORKSPACE_IDS).one()
        session.info[WORKSPACES_KEY] = frozenset(row[1] or ())
    else:
        raise ContextMissing("request-path transaction without a bootstrap or tenant context")


def register_listener() -> None:
    """Attach the listener to :class:`RequestSession` once (idempotent)."""
    if not event.contains(RequestSession, "after_begin", _after_begin):
        event.listen(RequestSession, "after_begin", _after_begin)


register_listener()


def create_request_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, sync_session_class=RequestSession, autoflush=False, expire_on_commit=False)


@asynccontextmanager
async def _session_with(factory: async_sessionmaker[AsyncSession], context) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        session.info[CONTEXT_KEY] = context
        try:
            async with session.begin():
                await session.connection()  # runs the listener now, before the caller's first query
                yield session
        finally:
            session.info.pop(CONTEXT_KEY, None)
            session.info.pop(WORKSPACES_KEY, None)


def bootstrap_session(factory: async_sessionmaker[AsyncSession], context: BootstrapContext):
    if not isinstance(context, BootstrapContext):
        raise TypeError("bootstrap_session takes a BootstrapContext")
    return _session_with(factory, context)


def tenant_session(factory: async_sessionmaker[AsyncSession], user: ProvisionedUser):
    """A tenant unit of work for an active provisioned user; the workspace set is in ``info[WORKSPACES_KEY]``."""
    if not isinstance(user, ProvisionedUser):
        raise TypeError("tenant_session takes a ProvisionedUser")
    if user.status != "active":
        raise InactivePrincipal("tenant transaction refused for a non-active user")
    return _session_with(factory, TenantContext(user.user_id))


async def provision(factory: async_sessionmaker[AsyncSession], context: BootstrapContext) -> ProvisionedUser:
    """Find or create the principal's user, personal workspace and owner membership (one committed transaction)."""
    async with bootstrap_session(factory, context) as session:
        connection = await session.connection()
        row = (await connection.exec_driver_sql(
            ENSURE_PRINCIPAL, {"issuer": context.issuer, "subject": context.subject, "email": context.email})).one()
    return ProvisionedUser(user_id=row[0], status=row[1])


def unapproved(statements: Iterable[str]) -> list[str]:
    """Statements that are not exactly one of :data:`APPROVED_STATEMENTS` (C14b; fail closed)."""
    return [statement for statement in statements if statement not in APPROVED_STATEMENTS]
