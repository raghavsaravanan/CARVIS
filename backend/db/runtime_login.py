"""Runtime-login validation and the owner-run grant command (M2 B2a; doc 04 "Roles").

The deployment's runtime login holds no privileges of its own. It is a member of ``carvis_app`` and
``carvis_bootstrap`` **with INHERIT FALSE, SET TRUE** and of nothing else, and every request
transaction selects one of them with ``SET LOCAL ROLE``. This module is the single definition of
what a safe runtime login is; the readiness self-check (:mod:`db.readiness`) runs the same query.

Usage (from ``backend/``, connecting with ``CARVIS_MIGRATION_DATABASE_URL``; owner-run at
provisioning or locally, never on deploy)::

    python -m db.runtime_login check <login>   # validate only; grants nothing
    python -m db.runtime_login grant <login>   # validate, grant the two memberships, validate again

Exit status: 0 safe, 1 validation failed (conditions are named), 2 usage or configuration error.
Output names conditions only; no URL, credential or value is ever printed.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Iterable

from db.roles import APP_ROLE, BOOTSTRAP_ROLE

RUNTIME_MEMBERSHIPS = (APP_ROLE, BOOTSTRAP_ROLE)
LOGIN_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Every condition a runtime login must meet, as one query returning the names of violated conditions.
# ``%(login)s`` is the login name. Ownership and every ACL reference (any object kind, including
# columns, databases and shared objects) come from pg_shdepend for **every database in the cluster**
# (another database's objects are as unsafe as this one's); role memberships leave no pg_shdepend
# rows and are checked in pg_auth_members. Every catalog is schema-qualified so a hostile search_path changes nothing.
LOGIN_CHECK_SQL = f"""
WITH r AS (SELECT oid, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls
           FROM pg_catalog.pg_roles WHERE rolname = %(login)s),
     wanted AS (SELECT oid, rolname FROM pg_catalog.pg_roles WHERE rolname IN ('{APP_ROLE}', '{BOOTSTRAP_ROLE}'))
SELECT 'missing' WHERE NOT EXISTS (SELECT 1 FROM r)
UNION ALL SELECT 'nologin' FROM r WHERE NOT rolcanlogin
UNION ALL SELECT 'superuser' FROM r WHERE rolsuper
UNION ALL SELECT 'createrole' FROM r WHERE rolcreaterole
UNION ALL SELECT 'createdb' FROM r WHERE rolcreatedb
UNION ALL SELECT 'replication' FROM r WHERE rolreplication
UNION ALL SELECT 'bypassrls' FROM r WHERE rolbypassrls
UNION ALL SELECT 'owns_objects' FROM r WHERE EXISTS (
      SELECT 1 FROM pg_catalog.pg_shdepend d
      WHERE d.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass AND d.refobjid = r.oid
        AND d.deptype = 'o')
UNION ALL SELECT 'acl_entries' FROM r WHERE EXISTS (
      SELECT 1 FROM pg_catalog.pg_shdepend d
      WHERE d.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass AND d.refobjid = r.oid
        AND d.deptype IN ('a', 'r', 'i'))
UNION ALL SELECT 'role_settings' FROM r WHERE EXISTS (
      SELECT 1 FROM pg_catalog.pg_db_role_setting WHERE setrole = r.oid)
UNION ALL SELECT 'default_acl' FROM r WHERE
      EXISTS (SELECT 1 FROM pg_catalog.pg_default_acl d WHERE d.defaclrole = r.oid)
   OR EXISTS (SELECT 1 FROM pg_catalog.pg_default_acl d, pg_catalog.aclexplode(d.defaclacl) a
              WHERE a.grantee = r.oid)
UNION ALL SELECT 'has_members' FROM r WHERE EXISTS (
      SELECT 1 FROM pg_catalog.pg_auth_members WHERE roleid = r.oid)
UNION ALL SELECT 'unexpected_membership' FROM r WHERE EXISTS (
      SELECT 1 FROM pg_catalog.pg_auth_members m
      WHERE m.member = r.oid
        AND NOT (m.roleid IN (SELECT oid FROM wanted)
                 AND NOT m.admin_option AND NOT m.inherit_option AND m.set_option))
UNION ALL SELECT 'duplicate_membership_' || w.rolname FROM r, wanted w WHERE (
      SELECT count(*) FROM pg_catalog.pg_auth_members m WHERE m.member = r.oid AND m.roleid = w.oid) > 1
UNION ALL SELECT 'missing_membership_' || w.rolname FROM r, wanted w
WHERE %(require_memberships)s AND NOT EXISTS (
      SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member = r.oid AND m.roleid = w.oid)
UNION ALL SELECT 'missing_role_' || name FROM pg_catalog.unnest(ARRAY['{APP_ROLE}', '{BOOTSTRAP_ROLE}']) AS name
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = name)
"""


class UsageError(RuntimeError):
    """Bad arguments or configuration. Names the problem, never a value."""


def check_params(login: str, require_memberships: bool = True) -> dict[str, object]:
    return {"login": login, "require_memberships": require_memberships}


def problems(connection, login: str, require_memberships: bool = True) -> list[str]:
    """The violated conditions for ``login`` (sorted, de-duplicated) on a psycopg connection."""
    rows = connection.execute(LOGIN_CHECK_SQL, check_params(login, require_memberships)).fetchall()
    return sorted({row[0] for row in rows})


def _validate_name(login: str) -> str:
    if not LOGIN_NAME.fullmatch(login) or login.startswith("carvis_"):
        raise UsageError("The login name must be a plain lower-case identifier that does not start with carvis_.")
    return login


def _connect():
    import psycopg

    from settings import MIGRATION_DATABASE_URL_ENV, normalize_database_url

    status, url = normalize_database_url(os.getenv(MIGRATION_DATABASE_URL_ENV))
    if status != "configured" or url is None:
        raise UsageError(f"{MIGRATION_DATABASE_URL_ENV} must be a supported PostgreSQL URL.")
    from sqlalchemy.engine import make_url

    conninfo = make_url(url.reveal()).set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        return psycopg.connect(conninfo, connect_timeout=5, prepare_threshold=None)
    except psycopg.Error:
        raise UsageError(f"Could not connect with {MIGRATION_DATABASE_URL_ENV}.") from None


def grant(connection, login: str) -> list[str]:
    """Validate, grant the missing memberships with INHERIT FALSE, SET TRUE, validate again.

    Runs in the caller's transaction; the caller commits only when the returned list is empty.
    """
    from psycopg import sql

    before = problems(connection, login, require_memberships=False)
    if before:
        return before
    for role in RUNTIME_MEMBERSHIPS:
        connection.execute(sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
            sql.Identifier(role), sql.Identifier(login)))
    return problems(connection, login, require_memberships=True)


def run(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 2 or args[0] not in ("check", "grant"):
        print("usage: python -m db.runtime_login check|grant <login>", file=sys.stderr)
        return 2
    command, login = args
    try:
        _validate_name(login)
        connection = _connect()
    except UsageError as exc:
        print(f"runtime login: {exc}", file=sys.stderr)
        return 2
    import psycopg

    try:
        with connection:
            found = problems(connection, login) if command == "check" else grant(connection, login)
            if found:
                connection.rollback()
                print(f"runtime login is not safe: {', '.join(found)}", file=sys.stderr)
                return 1
    except psycopg.Error as exc:
        # SQLSTATE only: messages can name objects or values.
        print(f"runtime login: database error {getattr(exc, 'sqlstate', None) or type(exc).__name__}",
              file=sys.stderr)
        return 1
    print(f"runtime login {command}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
