"""Catalog check for the CARVIS privilege and RLS model (M2 B2b-1; doc 04 "Validation" 1, 10, 13, 15).

:func:`violations` returns violation codes (empty when the catalog is sound). Migration
``0004_identity`` runs it as a post-condition, the tests run it after upgrade and downgrade, and later
packages extend :data:`IDENTITY_TABLES`, :data:`DEFINER_ALLOW_LIST` and :data:`EXACT_TABLE_PRIVILEGES`
when they add tables, definer functions or grants. It reads only catalogs, schema-qualified, so a
hostile ``search_path`` changes nothing.

Rules (both CARVIS schemas, ``carvis`` and ``carvis_migrations``):

- every table in ``carvis`` with a ``workspace_id`` column, and every identity table, has row-level
  security enabled **and forced**;
- the CARVIS runtime and definer roles are NOLOGIN, have no elevated attribute (superuser, createdb,
  createrole, replication, BYPASSRLS) and are members of no role; the runtime roles own no relation;
- no ACL on a CARVIS schema, relation, column, routine or type grants anything to ``PUBLIC`` or an
  issuer role, and no routine or non-array type has a NULL ACL (NULL means defaults that include
  ``PUBLIC``);
- every ``SECURITY DEFINER`` routine is allow-listed with its exact ACL, has ``search_path`` pinned to exactly
  ``pg_catalog, pg_temp`` and an owner that is not a superuser and owns no relation;
- each definer owner has no member except PostgreSQL 16's ADMIN-only grant (no SET, no INHERIT) and
  no ``CREATE`` on either CARVIS schema;
- the listed roles hold exactly the listed privileges on the identity tables, no more and no less.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from db.roles import (APP_ROLE, BOOTSTRAP_ROLE, ISSUER_ROLES, METADATA_SCHEMA, OWNER_ROLE, PROVISIONER_ROLE, SCHEMA,
                      WORKER_ROLE)

IDENTITY_TABLES = ("users", "workspaces", "memberships")
CHECKED_ROLES = (APP_ROLE, WORKER_ROLE, BOOTSTRAP_ROLE, PROVISIONER_ROLE)
NON_OWNING_ROLES = (APP_ROLE, WORKER_ROLE, BOOTSTRAP_ROLE, PROVISIONER_ROLE)
DEFINER_OWNERS = (PROVISIONER_ROLE,)
# routine signature -> exact ACL entries "grantee=privileges/grantor"
DEFINER_ALLOW_LIST = {
    f"{SCHEMA}.ensure_principal(text,text,text)": {
        f"{PROVISIONER_ROLE}=X/{PROVISIONER_ROLE}", f"{BOOTSTRAP_ROLE}=X/{PROVISIONER_ROLE}"},
}
# Invoker routines whose ACL is fixed exactly (other invoker routines only need no PUBLIC/issuer entry).
EXACT_ROUTINE_ACLS = {
    f"{SCHEMA}.uuid_v7()": {f"{OWNER_ROLE}=X/{OWNER_ROLE}", f"{PROVISIONER_ROLE}=X/{OWNER_ROLE}"},
}
# (role, table) -> set of (privilege, column or "" for table level). Roles not listed for a table
# must hold nothing on it.
EXACT_TABLE_PRIVILEGES: dict[tuple[str, str], set[tuple[str, str]]] = {
    (APP_ROLE, "users"): {("SELECT", "")},
    (APP_ROLE, "workspaces"): {("SELECT", "")},
    (APP_ROLE, "memberships"): {("SELECT", "")},
    (WORKER_ROLE, "users"): {("SELECT", "")},
    (WORKER_ROLE, "workspaces"): {("SELECT", "")},
    (WORKER_ROLE, "memberships"): {("SELECT", "")},
    (PROVISIONER_ROLE, "users"): {("SELECT", c) for c in ("id", "status", "auth_issuer", "auth_subject")}
    | {("INSERT", c) for c in ("auth_issuer", "auth_subject", "email")},
    (PROVISIONER_ROLE, "workspaces"): {("SELECT", c) for c in ("id", "kind", "personal_owner_user_id")}
    | {("INSERT", "")},
    (PROVISIONER_ROLE, "memberships"): {("SELECT", c) for c in ("workspace_id", "user_id", "role")}
    | {("INSERT", "")},
}
ELEVATED = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls", "rolcanlogin")
NOT_ARRAY = ("NOT (t.typelem <> 0 AND t.typsubscript = "
             "'pg_catalog.array_subscript_handler'::pg_catalog.regproc)")
# The only accepted definer search_path: catalogs first, pg_temp last, nothing caller-writable.
PINNED_SEARCH_PATH = "search_path=pg_catalog, pg_temp"
PRIVILEGE_NAMES = {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}


def _rows(connection: Connection, sql: str, **params) -> list:
    return list(connection.execute(text(sql), params).all())


def violations(connection: Connection) -> list[str]:
    found: list[str] = []
    schemas = [SCHEMA, METADATA_SCHEMA]
    issuers = list(ISSUER_ROLES)

    # RLS enabled and forced.
    for name, enabled, forced in _rows(connection, """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')
              AND (c.relname = ANY(:identity) OR EXISTS (
                   SELECT 1 FROM pg_catalog.pg_attribute a WHERE a.attrelid = c.oid
                   AND a.attname = 'workspace_id' AND NOT a.attisdropped))""",
                                       schema=SCHEMA, identity=list(IDENTITY_TABLES)):
        if not (enabled and forced):
            found.append(f"rls_not_forced:{name}")

    # Role attributes, memberships held and ownership.
    for role in CHECKED_ROLES:
        rows = _rows(connection, f"SELECT {', '.join(ELEVATED)} FROM pg_catalog.pg_roles WHERE rolname = :r", r=role)
        if not rows:
            found.append(f"role_missing:{role}")
            continue
        for attribute, value in zip(ELEVATED, rows[0]):
            if value:
                found.append(f"role_attribute:{role}:{attribute}")
        if _rows(connection, "SELECT 1 FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r "
                             "ON r.oid = m.member WHERE r.rolname = :r", r=role):
            found.append(f"role_member_of_another:{role}")
    for role in NON_OWNING_ROLES:
        if _rows(connection, "SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_roles r ON r.oid = c.relowner "
                             "WHERE r.rolname = :r", r=role):
            found.append(f"role_owns_relation:{role}")

    # PUBLIC or issuer entries anywhere in the CARVIS schemas; NULL ACLs on routines and types.
    grantees = """(SELECT 0::oid UNION ALL SELECT oid FROM pg_catalog.pg_roles WHERE rolname = ANY(:issuers))"""
    acl_queries = {
        "schema": "SELECT n.nspname FROM pg_catalog.pg_namespace n, pg_catalog.aclexplode(n.nspacl) a "
                  f"WHERE n.nspname = ANY(:schemas) AND a.grantee IN {grantees}",
        "relation": "SELECT n.nspname || '.' || c.relname FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace, pg_catalog.aclexplode(c.relacl) a "
                    f"WHERE n.nspname = ANY(:schemas) AND a.grantee IN {grantees}",
        "column": "SELECT n.nspname || '.' || c.relname || '.' || t.attname FROM pg_catalog.pg_attribute t "
                  "JOIN pg_catalog.pg_class c ON c.oid = t.attrelid JOIN pg_catalog.pg_namespace n "
                  "ON n.oid = c.relnamespace, pg_catalog.aclexplode(t.attacl) a "
                  f"WHERE n.nspname = ANY(:schemas) AND a.grantee IN {grantees}",
        "routine": "SELECT p.oid::pg_catalog.regprocedure::text FROM pg_catalog.pg_proc p "
                   "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace, pg_catalog.aclexplode(p.proacl) a "
                   f"WHERE n.nspname = ANY(:schemas) AND a.grantee IN {grantees}",
        "type": "SELECT n.nspname || '.' || t.typname FROM pg_catalog.pg_type t "
                "JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace, pg_catalog.aclexplode(t.typacl) a "
                f"WHERE n.nspname = ANY(:schemas) AND a.grantee IN {grantees}",
        "routine_null_acl": "SELECT p.oid::pg_catalog.regprocedure::text FROM pg_catalog.pg_proc p "
                            "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = ANY(:schemas) AND p.proacl IS NULL",
        "type_null_acl": "SELECT n.nspname || '.' || t.typname FROM pg_catalog.pg_type t "
                         "JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace "
                         f"WHERE n.nspname = ANY(:schemas) AND {NOT_ARRAY} AND t.typacl IS NULL",
    }
    for kind, sql in acl_queries.items():
        for (name,) in _rows(connection, sql, schemas=schemas, issuers=issuers):
            found.append(f"public_or_issuer_{kind}:{name}")

    # SECURITY DEFINER routines.
    for signature, config, owner, owner_super, acl in _rows(connection, """
            SELECT p.oid::pg_catalog.regprocedure::text, p.proconfig, r.rolname, r.rolsuper,
                   ARRAY(SELECT pg_catalog.unnest(p.proacl)::text ORDER BY 1)
            FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_catalog.pg_roles r ON r.oid = p.proowner
            WHERE n.nspname = ANY(:schemas) AND p.prosecdef""", schemas=schemas):
        expected = DEFINER_ALLOW_LIST.get(signature)
        if expected is None:
            found.append(f"definer_not_allowed:{signature}")
            continue
        if set(acl or []) != expected:
            found.append(f"definer_acl:{signature}")
        if PINNED_SEARCH_PATH not in (config or []):
            found.append(f"definer_search_path:{signature}")
        if owner_super or _rows(connection, "SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_roles r "
                                            "ON r.oid = c.relowner WHERE r.rolname = :r", r=owner):
            found.append(f"definer_owner:{signature}")
    for signature, expected in EXACT_ROUTINE_ACLS.items():
        # Matched through the catalog (to_regprocedure needs USAGE on the schema).
        rows = _rows(connection, "SELECT ARRAY(SELECT pg_catalog.unnest(p.proacl)::text ORDER BY 1) "
                                 "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
                                 "WHERE n.nspname = ANY(:schemas) AND p.oid::pg_catalog.regprocedure::text = :s",
                     s=signature, schemas=schemas)
        if rows and set(rows[0][0] or []) != expected:
            found.append(f"routine_acl:{signature}")

    # Definer owners: only the ADMIN-only member; no CREATE on carvis.
    for role in DEFINER_OWNERS:
        for member, admin, inherit, can_set in _rows(connection, """
                SELECT mr.rolname, m.admin_option, m.inherit_option, m.set_option
                FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r ON r.oid = m.roleid
                JOIN pg_catalog.pg_roles mr ON mr.oid = m.member WHERE r.rolname = :r""", r=role):
            if inherit or can_set or not admin:
                found.append(f"definer_owner_member:{role}:{member}")
        for schema in schemas:
            if _rows(connection, "SELECT 1 WHERE pg_catalog.has_schema_privilege(:r, :s, 'CREATE')", r=role, s=schema):
                found.append(f"definer_owner_create:{role}:{schema}")

    # Exact privileges on the identity tables.
    present = {row[0] for row in _rows(connection, """
            SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relname = ANY(:tables) AND c.relkind = 'r'""",
                                       schema=SCHEMA, tables=list(IDENTITY_TABLES))}
    for table in sorted(present):
        held: dict[str, set[tuple[str, str]]] = {}
        for grantee, privilege, column in _rows(connection, """
                SELECT r.rolname, a.privilege_type, '' FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace, pg_catalog.aclexplode(c.relacl) a
                JOIN pg_catalog.pg_roles r ON r.oid = a.grantee
                WHERE n.nspname = :schema AND c.relname = :t
                UNION ALL
                SELECT r.rolname, a.privilege_type, t.attname FROM pg_catalog.pg_attribute t
                JOIN pg_catalog.pg_class c ON c.oid = t.attrelid JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace, pg_catalog.aclexplode(t.attacl) a
                JOIN pg_catalog.pg_roles r ON r.oid = a.grantee
                WHERE n.nspname = :schema AND c.relname = :t""", schema=SCHEMA, t=table):
            if grantee == OWNER_ROLE:
                continue
            held.setdefault(grantee, set()).add((privilege, column))
        for role in set(held) | {r for r, t in EXACT_TABLE_PRIVILEGES if t == table}:
            if held.get(role, set()) != EXACT_TABLE_PRIVILEGES.get((role, table), set()):
                found.append(f"table_privileges:{role}:{table}")
    return sorted(set(found))
