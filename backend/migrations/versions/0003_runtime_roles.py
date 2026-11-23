"""Bootstrap and provisioner roles; function default privileges; issuer-role revokes (M2 B2a).

Specification: ``docs/architecture/04-identity-tenancy-rls.md`` ("Roles", "Function privileges",
"Function ownership and migration membership"); ADR-0002, ADR-0003.

Upgrade, in this revision's single transaction (any failure rolls everything back):

1. Preflight (fail closed, before any change):
   - PostgreSQL 16+; the login may create roles; neither new role exists (never adopted).
   - The B1 roles (``carvis_owner``, ``carvis_app``, ``carvis_worker``) are rechecked, because they
     may have changed since 0002 validated them: NOLOGIN with no elevated attribute (a
     ``BYPASSRLS`` runtime role would defeat RLS); members of no role; no members except the
     migration login's ADMIN-only grant (and 0002's ``SET`` grant on ``carvis_owner``); no
     role-level settings; no default-ACL rows; ownership only of ``carvis`` objects
     (``carvis_owner``) or nothing (runtime roles); and ACL references only to what 0002 granted
     (``USAGE`` on ``carvis`` and ``carvis_migrations``, ``SELECT`` on the version table).
   - The member allow-list above also refuses any issuer role (``anon``, ``authenticated``,
     ``service_role``) holding membership in a CARVIS role, which would otherwise inherit its access.
2. ``createrole_self_grant`` is pinned to empty, then ``carvis_bootstrap`` and ``carvis_provisioner``
   are created NOLOGIN with no elevated attribute and this revision's marker. A non-superuser
   ``CREATEROLE`` login keeps PostgreSQL 16's automatic ADMIN-only grant on them (INHERIT FALSE,
   SET FALSE): the accepted migration-administrator authority (owner, 2026-11-23).
3. As ``carvis_owner``: USAGE on ``carvis`` for both roles, and the global (no ``IN SCHEMA``)
   ``ALTER DEFAULT PRIVILEGES FOR ROLE carvis_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC``.
4. The same default revoke for ``carvis_provisioner``, run as that role through a temporary
   ``WITH INHERIT FALSE, SET TRUE`` grant to a non-superuser login, revoked before the step ends.
5. Everything on the ``carvis`` and ``carvis_migrations`` schemas and their objects (tables,
   sequences, routines, and every type that accepts privileges: enums, domains (including domains
   over arrays), composites, ranges, multiranges and tables' row types; true array types take their
   element type's) is revoked from
   ``PUBLIC`` and from the issuer roles that exist, each revoke issued as the object owner.
6. Post-conditions, checked before commit: no ``PUBLIC`` or issuer-role entry remains in any ACL on
   those schemas, their relations, columns, routines and types (a routine or type with a NULL ACL
   counts, since NULL means defaults that include PUBLIC); the new roles have no member except the
   migration login's ADMIN-only grant (so no issuer role either) and no ``CREATE`` on ``carvis``.

Downgrade restores the two default-privilege rows (removing their ``pg_default_acl`` entries),
revokes USAGE and drops only roles carrying this revision's marker. The step-5 revokes are not
restored: CARVIS never made those grants, and leaving them revoked is fail-closed.

Test hook: forced failures for the rollback tests are honored only when the deployment environment
(``CARVIS_ENV``) is ``local`` and ``CARVIS_TEST_FAIL_AT`` names a step; nothing else reads it.

Revision ID: 0003_runtime_roles
Revises: 0002_roles
Create Date: 2026-11-23
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from alembic import op
from sqlalchemy import text

from db.roles import (B2A_ROLES, BOOTSTRAP_ROLE, ISSUER_ROLES, MARKER_0003, METADATA_SCHEMA, OWNER_ROLE,
                      PROVISIONER_ROLE, ROLES, RUNTIME_ROLES, SCHEMA, VERSION_TABLE, as_owner, as_role)

revision = "0003_runtime_roles"
down_revision = "0002_roles"
branch_labels = None
depends_on = None

MINIMUM_SERVER_VERSION = 160000
ELEVATED_ATTRIBUTES = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
FAIL_STEPS = ("create_roles", "owner_privileges", "temporary_grant", "provisioner_defaults", "issuer_revokes",
              "downgrade_defaults")
CURRENT_DB = "(SELECT oid FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database())"


class RuntimeRolesMigrationError(RuntimeError):
    """The database cannot take this revision safely. Names roles and conditions only."""


def _scalar(sql: str, **params):
    return op.get_bind().execute(text(sql), params).scalar()


def _rows(sql: str, **params):
    return op.get_bind().execute(text(sql), params).mappings().all()


def _exec(sql: str) -> None:
    op.get_bind().execute(text(sql))


def _maybe_fail(step: str) -> None:
    from webhook_auth import LOCAL, deployment_environment

    if deployment_environment() == LOCAL and os.getenv("CARVIS_TEST_FAIL_AT") == step:
        raise RuntimeRolesMigrationError(f"forced failure at {step} (test hook)")


def _login() -> tuple[str, bool, bool]:
    row = _rows("SELECT rolname, rolsuper, rolcreaterole FROM pg_catalog.pg_roles WHERE rolname = current_user")[0]
    return row["rolname"], row["rolsuper"], row["rolcreaterole"]


# --- Preflight -----------------------------------------------------------------------------------

def _check_b1_role(role: str, login: str) -> None:
    attributes = _rows(f"SELECT rolcanlogin, {', '.join(ELEVATED_ATTRIBUTES)} FROM pg_catalog.pg_roles "
                       "WHERE rolname = :r", r=role)
    if not attributes:
        raise RuntimeRolesMigrationError(f"Role {role} is missing; revision 0002_roles must be applied first.")
    elevated = [name for name in ELEVATED_ATTRIBUTES if attributes[0][name]]
    if elevated or attributes[0]["rolcanlogin"]:
        raise RuntimeRolesMigrationError(f"Role {role} has gained LOGIN or an elevated attribute since 0002.")
    if _scalar("SELECT count(*) FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r ON r.oid = m.member "
               "WHERE r.rolname = :r", r=role):
        raise RuntimeRolesMigrationError(f"Role {role} is a member of another role.")
    # Members: only the migration login's automatic ADMIN-only grant, plus (carvis_owner) 0002's own
    # INHERIT FALSE, SET TRUE grant by the login.
    members = _rows(
        "SELECT mr.rolname AS member, gr.rolname AS grantor, m.admin_option, m.inherit_option, m.set_option "
        "FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r ON r.oid = m.roleid "
        "JOIN pg_catalog.pg_roles mr ON mr.oid = m.member JOIN pg_catalog.pg_roles gr ON gr.oid = m.grantor "
        "WHERE r.rolname = :r", r=role)
    for member in members:
        admin_only = (member["admin_option"] and not member["inherit_option"] and not member["set_option"]
                      and member["grantor"] != login)
        owner_set = (role == OWNER_ROLE and member["grantor"] == login and not member["admin_option"]
                     and not member["inherit_option"] and member["set_option"])
        if member["member"] != login or not (admin_only or owner_set):
            raise RuntimeRolesMigrationError(f"Role {role} has members other than the migration login's grants.")
    if _scalar("SELECT count(*) FROM pg_catalog.pg_db_role_setting s JOIN pg_catalog.pg_roles r "
               "ON r.oid = s.setrole WHERE r.rolname = :r", r=role):
        raise RuntimeRolesMigrationError(f"Role {role} has role-level settings.")
    if _scalar("SELECT count(*) FROM pg_catalog.pg_default_acl d WHERE d.defaclrole = "
               "(SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :r)", r=role) or _scalar(
            "SELECT count(*) FROM pg_catalog.pg_default_acl d, pg_catalog.aclexplode(d.defaclacl) a "
            "WHERE a.grantee = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :r)", r=role):
        raise RuntimeRolesMigrationError(f"Role {role} appears in a default ACL.")
    if _unexpected_dependencies(role):
        raise RuntimeRolesMigrationError(f"Role {role} owns or holds privileges on objects 0002 did not grant.")


def _unexpected_dependencies(role: str) -> int:
    """pg_shdepend rows for ``role`` beyond what 0002 created.

    Allowed: ``carvis_owner`` owning schema ``carvis`` and objects inside it; ``carvis_app`` and
    ``carvis_worker`` referenced in the ACLs of schemas ``carvis`` and ``carvis_migrations`` and of the
    version table, all in this database. Everything else (other ownership, any other ACL or policy
    reference, anything in another database of the cluster, any shared object such as a database or
    tablespace) is unexpected.
    """
    return _scalar(f"""
        SELECT count(*) FROM pg_catalog.pg_shdepend d
        WHERE d.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass
          AND d.refobjid = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :r)
          AND NOT (
            (:r = :owner AND d.deptype = 'o' AND d.dbid = {CURRENT_DB} AND (
               (d.classid = 'pg_catalog.pg_namespace'::pg_catalog.regclass
                  AND d.objid = (SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = :schema))
               OR (d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass AND d.objid IN (
                  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = :schema))
               OR (d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass AND d.objid IN (
                  SELECT p.oid FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                  WHERE n.nspname = :schema))
               OR (d.classid = 'pg_catalog.pg_type'::pg_catalog.regclass AND d.objid IN (
                  SELECT t.oid FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
                  WHERE n.nspname = :schema))))
            OR (:r = ANY(:runtime) AND d.deptype = 'a' AND d.dbid = {CURRENT_DB} AND d.objsubid = 0 AND (
               (d.classid = 'pg_catalog.pg_namespace'::pg_catalog.regclass AND d.objid IN (
                  SELECT oid FROM pg_catalog.pg_namespace WHERE nspname IN (:schema, :meta)))
               OR (d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass AND d.objid = (
                  SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = :meta AND c.relname = :version))))
          )""", r=role, owner=OWNER_ROLE, schema=SCHEMA, meta=METADATA_SCHEMA, version=VERSION_TABLE,
        runtime=list(RUNTIME_ROLES))


def _preflight(login: str, superuser: bool, createrole: bool) -> None:
    if int(_scalar("SHOW server_version_num")) < MINIMUM_SERVER_VERSION:
        raise RuntimeRolesMigrationError("PostgreSQL 16 or later is required.")
    if not (superuser or createrole):
        raise RuntimeRolesMigrationError("The migration login needs CREATEROLE to create the CARVIS roles.")
    for role in B2A_ROLES:
        if _scalar("SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname = :r", r=role):
            raise RuntimeRolesMigrationError(f"Role {role} already exists; refusing to adopt it.")
    for role in ROLES:
        _check_b1_role(role, login)


# --- Steps ---------------------------------------------------------------------------------------

def _existing_issuer_roles() -> list[str]:
    return [row["rolname"] for row in _rows(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(:r) ORDER BY 1", r=list(ISSUER_ROLES))]


@contextmanager
def _with_temporary_set(role: str, superuser: bool) -> Iterator[None]:
    """Temporary ``WITH INHERIT FALSE, SET TRUE`` membership for a non-superuser login (doc 04)."""
    if not superuser:
        _exec(f"GRANT {role} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE")
    with as_role(op.get_bind(), role):
        yield
    _maybe_fail("temporary_grant")
    # Revoked only after success: on failure the whole migration transaction rolls back, which
    # removes the grant too (a revoke in an aborted transaction would mask the original error).
    if not superuser:
        _exec(f"REVOKE {role} FROM CURRENT_USER GRANTED BY CURRENT_USER")


# Types that accept privileges: everything except true array types, which PostgreSQL identifies by an
# element type and the array subscript handler (it derives their privileges from the element type and
# refuses GRANT/REVOKE on them). A domain over an array is not an array type and is included.
NOT_ARRAY = ("NOT (t.typelem <> 0 AND t.typsubscript = "
             "'pg_catalog.array_subscript_handler'::pg_catalog.regproc)")
PRIVILEGED_TYPES = f"""
    SELECT pg_catalog.format('%I.%I', n.nspname, t.typname) AS name
    FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = :schema AND {NOT_ARRAY} ORDER BY 1"""


def _revoke_types(schema: str, grantee: str) -> None:
    for row in _rows(PRIVILEGED_TYPES, schema=schema):
        _exec(f"REVOKE ALL ON TYPE {row['name']} FROM {grantee}")


def _revoke_everything(grantee: str) -> None:
    """Revoke as each object's owner: ``carvis`` objects belong to carvis_owner (a REVOKE by anyone
    else silently removes nothing), ``carvis_migrations`` objects to the migration login."""
    with as_owner(op.get_bind()):
        _exec(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM {grantee}")
        for kind in ("TABLES", "SEQUENCES", "ROUTINES"):
            _exec(f"REVOKE ALL ON ALL {kind} IN SCHEMA {SCHEMA} FROM {grantee}")
        _revoke_types(SCHEMA, grantee)
    _exec(f"REVOKE ALL ON SCHEMA {METADATA_SCHEMA} FROM {grantee}")
    for kind in ("TABLES", "SEQUENCES", "ROUTINES"):
        _exec(f"REVOKE ALL ON ALL {kind} IN SCHEMA {METADATA_SCHEMA} FROM {grantee}")
    _revoke_types(METADATA_SCHEMA, grantee)


def _leftover_grants() -> int:
    """ACL entries for PUBLIC (grantee 0) or an issuer role on CARVIS schemas and their objects.

    A routine or (non-array) type with a NULL ACL counts too: NULL means the defaults, which include
    PUBLIC EXECUTE or USAGE.
    """
    return _scalar(f"""
        WITH grantees AS (SELECT 0::oid AS oid UNION ALL
                          SELECT oid FROM pg_catalog.pg_roles WHERE rolname = ANY(:issuers)),
             spaces AS (SELECT oid, nspacl FROM pg_catalog.pg_namespace WHERE nspname IN (:schema, :meta))
        SELECT
          (SELECT count(*) FROM spaces s, pg_catalog.aclexplode(s.nspacl) a
           WHERE a.grantee IN (SELECT oid FROM grantees))
        + (SELECT count(*) FROM pg_catalog.pg_class c, pg_catalog.aclexplode(c.relacl) a
           WHERE c.relnamespace IN (SELECT oid FROM spaces) AND a.grantee IN (SELECT oid FROM grantees))
        + (SELECT count(*) FROM pg_catalog.pg_attribute t JOIN pg_catalog.pg_class c ON c.oid = t.attrelid,
                  pg_catalog.aclexplode(t.attacl) a
           WHERE c.relnamespace IN (SELECT oid FROM spaces) AND a.grantee IN (SELECT oid FROM grantees))
        + (SELECT count(*) FROM pg_catalog.pg_proc p, pg_catalog.aclexplode(p.proacl) a
           WHERE p.pronamespace IN (SELECT oid FROM spaces) AND a.grantee IN (SELECT oid FROM grantees))
        + (SELECT count(*) FROM pg_catalog.pg_proc p
           WHERE p.pronamespace IN (SELECT oid FROM spaces) AND p.proacl IS NULL)
        + (SELECT count(*) FROM pg_catalog.pg_type t, pg_catalog.aclexplode(t.typacl) a
           WHERE t.typnamespace IN (SELECT oid FROM spaces) AND a.grantee IN (SELECT oid FROM grantees))
        + (SELECT count(*) FROM pg_catalog.pg_type t
           WHERE t.typnamespace IN (SELECT oid FROM spaces) AND {NOT_ARRAY} AND t.typacl IS NULL)""",
                   issuers=list(ISSUER_ROLES), schema=SCHEMA, meta=METADATA_SCHEMA)


def _postconditions(login: str, superuser: bool) -> None:
    if _leftover_grants():
        raise RuntimeRolesMigrationError("PUBLIC or an issuer role still holds a privilege on a CARVIS object.")
    allowed = [] if superuser else [{"member": login, "admin_option": True, "inherit_option": False,
                                      "set_option": False}]
    for role in B2A_ROLES:
        members = _rows(
            "SELECT mr.rolname AS member, m.admin_option, m.inherit_option, m.set_option "
            "FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r ON r.oid = m.roleid "
            "JOIN pg_catalog.pg_roles mr ON mr.oid = m.member WHERE r.rolname = :r", r=role)
        if [dict(row) for row in members] != allowed:
            raise RuntimeRolesMigrationError(f"Role {role} has a member other than the ADMIN-only migration grant.")
        if _scalar("SELECT pg_catalog.has_schema_privilege(:r, :s, 'CREATE')", r=role, s=SCHEMA):
            raise RuntimeRolesMigrationError(f"Role {role} must not hold CREATE on schema {SCHEMA}.")


def upgrade() -> None:
    login, superuser, createrole = _login()
    _preflight(login, superuser, createrole)

    # 2. Roles. Pin createrole_self_grant so a provider- or login-level setting cannot add a
    #    self-granted SET/INHERIT membership next to PostgreSQL 16's automatic ADMIN-only grant.
    _exec("SET LOCAL createrole_self_grant = ''")
    for role in B2A_ROLES:
        _exec(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
        _exec(f"COMMENT ON ROLE {role} IS '{MARKER_0003}'")
    _maybe_fail("create_roles")

    # 3. Schema usage and carvis_owner's function default, as carvis_owner.
    with as_owner(op.get_bind()):
        _exec(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {BOOTSTRAP_ROLE}, {PROVISIONER_ROLE}")
        _exec(f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
    _maybe_fail("owner_privileges")

    # 4. carvis_provisioner's function default, as carvis_provisioner (temporary SET membership).
    with _with_temporary_set(PROVISIONER_ROLE, superuser):
        _exec(f"ALTER DEFAULT PRIVILEGES FOR ROLE {PROVISIONER_ROLE} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
    _maybe_fail("provisioner_defaults")

    # 5. Nothing for PUBLIC or the issuer roles on CARVIS schemas and objects.
    for grantee in ("PUBLIC", *_existing_issuer_roles()):
        _revoke_everything(grantee)
    _maybe_fail("issuer_revokes")

    # 6. Post-conditions.
    _postconditions(login, superuser)


def downgrade() -> None:
    _, superuser, _ = _login()
    marked = {row["rolname"] for row in _rows(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(:roles) "
        "AND pg_catalog.shobj_description(oid, 'pg_authid') = :m", roles=list(B2A_ROLES), m=MARKER_0003)}
    if PROVISIONER_ROLE in marked:
        with _with_temporary_set(PROVISIONER_ROLE, superuser):
            _exec(f"ALTER DEFAULT PRIVILEGES FOR ROLE {PROVISIONER_ROLE} GRANT EXECUTE ON FUNCTIONS TO PUBLIC")
    _maybe_fail("downgrade_defaults")
    with as_owner(op.get_bind()):
        _exec(f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} GRANT EXECUTE ON FUNCTIONS TO PUBLIC")
        for role in sorted(marked):
            _exec(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {role}")
    for role in sorted(marked):
        _exec(f"DROP ROLE {role}")
