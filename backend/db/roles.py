"""CARVIS database roles, schemas and the owner context used by migrations (M2 Track B1).

Ownership model: the migration login is whatever privileged login a deployment provides (chosen in
B2/B10). It owns only the ``carvis_migrations`` metadata schema and its Alembic version table. Every
CARVIS schema object is owned by ``carvis_owner`` (``NOLOGIN``); migrations create such objects inside
:func:`as_owner`, so ownership never depends on which login ran the migration. Roles are
cluster-wide, so one CARVIS database per PostgreSQL cluster is supported.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Connection

OWNER_ROLE = "carvis_owner"
APP_ROLE = "carvis_app"
WORKER_ROLE = "carvis_worker"
RUNTIME_ROLES = (APP_ROLE, WORKER_ROLE)
ROLES = (OWNER_ROLE, APP_ROLE, WORKER_ROLE)

SCHEMA = "carvis"
METADATA_SCHEMA = "carvis_migrations"
VERSION_TABLE = "alembic_version"
MARKER = "carvis:managed-by-migration:0002"


@contextmanager
def as_owner(connection: Connection) -> Iterator[None]:
    """Run statements as ``carvis_owner``, then return to the login role.

    ``SET LOCAL`` keeps the switch inside the migration's transaction; ``RESET ROLE`` restores the
    login before Alembic updates the version table, which ``carvis_owner`` has no rights on.
    """
    connection.execute(text(f"SET LOCAL ROLE {OWNER_ROLE}"))
    try:
        yield
    finally:
        connection.execute(text("RESET ROLE"))
