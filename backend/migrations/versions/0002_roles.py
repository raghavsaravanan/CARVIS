"""Provider-neutral CARVIS roles and the carvis schema (M2 B1).

Creates ``carvis_owner`` (owns CARVIS schema objects; migrations only), ``carvis_app`` (API runtime)
and ``carvis_worker`` (tenant-scoped jobs), all ``NOLOGIN`` with no elevated attributes, the ``carvis``
schema owned by ``carvis_owner``, and read access to the version table so the runtime roles can run
the readiness check without elevation. Grants touch only the CARVIS-owned ``carvis`` and
``carvis_migrations`` schemas and these three roles: nothing in ``public``, on the database, or on any
issuer- or host-specific role. Login credentials and which login runs migrations belong to B2/B10.

Fail closed, never modify: a pre-existing CARVIS role is validated and adopted only if compatible
(no elevated attribute, member of no role, no members except the migration login's administrative
grant on carvis_owner); otherwise the upgrade stops before any change. Downgrade drops only what this revision marked.
Requires PostgreSQL 16 or later.

Revision ID: 0002_roles
Revises: 0001_baseline
Create Date: 2026-11-22
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from db.roles import (APP_ROLE, MARKER, METADATA_SCHEMA, OWNER_ROLE, ROLES, RUNTIME_ROLES, SCHEMA, VERSION_TABLE,
                      WORKER_ROLE, as_owner)

revision = "0002_roles"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

ELEVATED_ATTRIBUTES = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
MINIMUM_SERVER_VERSION = 160000


class RoleMigrationError(RuntimeError):
    """The database cannot take this revision safely. Names roles and privileges only."""


def _scalar(sql: str, **params):
    return op.get_bind().execute(text(sql), params).scalar()


def _rows(sql: str, **params):
    return op.get_bind().execute(text(sql), params).mappings().all()


def _login() -> tuple[str, bool, bool]:
    row = _rows("SELECT rolname, rolsuper, rolcreaterole FROM pg_roles WHERE rolname = current_user")[0]
    return row["rolname"], row["rolsuper"], row["rolcreaterole"]


def _validate_existing(role: str, login: str, superuser: bool) -> None:
    attributes = _rows(f"SELECT rolcanlogin, {', '.join(ELEVATED_ATTRIBUTES)} FROM pg_roles WHERE rolname = :r",
                       r=role)[0]
    elevated = [name for name in ELEVATED_ATTRIBUTES if attributes[name]]
    if elevated:
        raise RoleMigrationError(f"Existing role {role} has incompatible attributes: {', '.join(elevated)}.")
    if role == OWNER_ROLE and attributes["rolcanlogin"]:
        raise RoleMigrationError(f"Existing role {role} must be NOLOGIN.")
    held = _scalar("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member "
                   "WHERE r.rolname = :r", r=role)
    if held:
        raise RoleMigrationError(f"Existing role {role} is a member of another role.")
    members = _rows(
        "SELECT mr.rolname AS member, gr.rolname AS grantor "
        "FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
        "JOIN pg_roles mr ON mr.oid = m.member JOIN pg_roles gr ON gr.oid = m.grantor WHERE r.rolname = :r",
        r=role)
    for member in members:
        # The only permitted member of any CARVIS role is the migration login, through a grant it did
        # not make itself (PostgreSQL 16's implicit CREATEROLE administrative grant). A grant by the
        # login would be added by upgrade and removed by downgrade, so it must not already exist.
        if member["member"] == login and member["grantor"] != login:
            continue
        if role == OWNER_ROLE:
            raise RoleMigrationError(f"Existing role {role} has members other than the migration login's "
                                     "administrative grant.")
        # B1 approves no runtime login yet (B2/B10), so any other member would silently inherit
        # CARVIS runtime access: fail closed rather than adopt it.
        raise RoleMigrationError(f"Existing role {role} has members; no runtime login is approved yet.")
    if not superuser and not _scalar("SELECT pg_has_role(current_user, :r, 'USAGE WITH ADMIN OPTION') "
                                     "OR pg_has_role(current_user, :r, 'MEMBER WITH ADMIN OPTION')", r=role):
        raise RoleMigrationError(f"The migration login needs ADMIN OPTION on existing role {role}.")


def upgrade() -> None:
    bind = op.get_bind()
    if int(_scalar("SHOW server_version_num")) < MINIMUM_SERVER_VERSION:
        raise RoleMigrationError("PostgreSQL 16 or later is required.")
    login, superuser, createrole = _login()
    existing = {row["rolname"] for row in _rows("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)",
                                                 roles=list(ROLES))}
    if set(ROLES) - existing and not (superuser or createrole):
        raise RoleMigrationError("The migration login needs CREATEROLE to create the CARVIS roles.")
    if not _scalar("SELECT has_database_privilege(current_database(), 'CREATE')"):
        raise RoleMigrationError("The migration login needs CREATE on the database.")
    if _scalar("SELECT count(*) FROM pg_namespace WHERE nspname = :s", s=SCHEMA):
        raise RoleMigrationError(f"Schema {SCHEMA} already exists; refusing to adopt it.")
    for role in ROLES:
        if role in existing:
            _validate_existing(role, login, superuser)

    for role in ROLES:
        if role not in existing:
            bind.execute(text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                              "NOBYPASSRLS"))
            bind.execute(text(f"COMMENT ON ROLE {role} IS '{MARKER}'"))
    if not superuser:
        bind.execute(text(f"GRANT {OWNER_ROLE} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE"))

    bind.execute(text(f"CREATE SCHEMA {SCHEMA} AUTHORIZATION {OWNER_ROLE}"))
    with as_owner(bind):
        bind.execute(text(f"COMMENT ON SCHEMA {SCHEMA} IS '{MARKER}'"))
        bind.execute(text(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC"))
        bind.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}, {WORKER_ROLE}"))

    runtime = ", ".join(RUNTIME_ROLES)
    bind.execute(text(f"GRANT USAGE ON SCHEMA {METADATA_SCHEMA} TO {runtime}"))
    bind.execute(text(f"GRANT SELECT ON {METADATA_SCHEMA}.{VERSION_TABLE} TO {runtime}"))


def downgrade() -> None:
    bind = op.get_bind()
    _, superuser, _ = _login()
    runtime = ", ".join(RUNTIME_ROLES)
    bind.execute(text(f"REVOKE SELECT ON {METADATA_SCHEMA}.{VERSION_TABLE} FROM {runtime}"))
    bind.execute(text(f"REVOKE USAGE ON SCHEMA {METADATA_SCHEMA} FROM {runtime}"))

    comment = _scalar("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = :s", s=SCHEMA)
    if comment != MARKER:
        raise RoleMigrationError(f"Schema {SCHEMA} is missing or was not created by this revision.")
    with as_owner(bind):
        bind.execute(text(f"DROP SCHEMA {SCHEMA} RESTRICT"))
    if not superuser:
        bind.execute(text(f"REVOKE {OWNER_ROLE} FROM CURRENT_USER GRANTED BY CURRENT_USER"))

    marked = _rows("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles) "
                   "AND shobj_description(oid, 'pg_authid') = :marker", roles=list(ROLES), marker=MARKER)
    for row in marked:
        bind.execute(text(f"DROP ROLE {row['rolname']}"))
