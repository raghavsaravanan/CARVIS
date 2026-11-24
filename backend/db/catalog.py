"""Catalog check for the CARVIS privilege and RLS model (M2 B2b-1; doc 04 "Validation" 1, 10, 13, 15).

:func:`violations` returns violation codes (empty when the catalog is sound). Migration
``0004_identity`` runs it as a post-condition, the tests run it after upgrade and downgrade, and later
packages extend :data:`IDENTITY_TABLES`, :data:`DEFINER_ALLOW_LIST` and :data:`EXACT_TABLE_PRIVILEGES`
when they add tables, definer functions or grants. It reads only catalogs, schema-qualified, and builds
routine signatures (argument types included) from catalog columns rather than ``regprocedure`` or
``oidvectortypes`` output, so the caller's ``search_path`` changes nothing.

Rules (both CARVIS schemas, ``carvis`` and ``carvis_migrations``):

- every table in ``carvis`` with a ``workspace_id`` column, and every identity table, has row-level
  security enabled **and forced**;
- the CARVIS runtime and definer roles are NOLOGIN, have no elevated attribute (superuser, createdb,
  createrole, replication, BYPASSRLS) and are members of no role;
- they own no object of any class in any database (``pg_shdepend`` owner entries, which include the
  database and schemas), except that a definer owner owns its allow-listed routines and its own
  default ACLs in this database;
- they have no effective ``CREATE`` (PUBLIC and inherited grants included) on either CARVIS schema or
  the database, and hold no grant option on the database or anything in the CARVIS schemas;
- no ACL on a CARVIS schema, relation, column, routine or type grants anything to ``PUBLIC`` or an
  issuer role, and no routine or non-array type has a NULL ACL (NULL means defaults that include
  ``PUBLIC``);
- every ``SECURITY DEFINER`` routine is allow-listed with its exact ACL, has ``search_path`` pinned to exactly
  ``pg_catalog, pg_temp`` and an owner that is not a superuser and owns no relation;
- every allow-listed definer is still ``SECURITY DEFINER`` and owned by its definer owner, and exists
  whenever the identity tables do;
- each definer owner has at most one member: PostgreSQL 16's ADMIN-only grant (no SET, no INHERIT) to
  the migration login named by the caller;
- the listed roles hold exactly the listed privileges on the identity tables, without grant option, no
  more and no less.
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
    f"{SCHEMA}.ensure_principal(pg_catalog.text,pg_catalog.text,pg_catalog.text)": {
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
# Routine signature as "schema.name(schema.type,...)", every part read from the catalogs, so the
# caller's search_path changes nothing (``regprocedure`` output and ``oidvectortypes`` both drop a
# schema that is on the path).
SIGNATURE = ("n.nspname || '.' || p.proname || '(' || COALESCE(("
             "SELECT pg_catalog.string_agg(tn.nspname || '.' || t.typname, ',' ORDER BY a.ord) "
             "FROM pg_catalog.unnest(p.proargtypes::pg_catalog.oid[]) WITH ORDINALITY AS a(typ, ord) "
             "JOIN pg_catalog.pg_type t ON t.oid = a.typ JOIN pg_catalog.pg_namespace tn ON tn.oid = t.typnamespace"
             "), '') || ')'")
PRIVILEGE_NAMES = {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}


def _rows(connection: Connection, sql: str, **params) -> list:
    return list(connection.execute(text(sql), params).all())


def violations(connection: Connection, migration_login: str | None = None) -> list[str]:
    """``migration_login`` is the only role allowed to hold the PostgreSQL 16 automatic ADMIN-only
    membership in a definer owner (doc 04); ``None`` allows no member at all."""
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
    # Ownership of any object class in any database, from pg_shdepend owner entries (deptype 'o'),
    # which PostgreSQL records for every object owned by a non-pinned role: relations, types,
    # routines, schemas, default ACLs, the database itself (dbid 0) and the rest. A definer owner may
    # own its allow-listed routines and its own default ACLs (0003) in this database; nothing else.
    for role in NON_OWNING_ROLES:
        for catalog, here, signature in _rows(connection, f"""
                SELECT (SELECT k.relname FROM pg_catalog.pg_class k WHERE k.oid = d.classid),
                       d.dbid = (SELECT db.oid FROM pg_catalog.pg_database db
                                 WHERE db.datname = pg_catalog.current_database()),
                       (SELECT {SIGNATURE} FROM pg_catalog.pg_proc p
                        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                        WHERE d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass AND p.oid = d.objid)
                FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles r ON r.oid = d.refobjid
                WHERE d.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass AND d.deptype = 'o'
                  AND r.rolname = :r""", r=role):
            if role in DEFINER_OWNERS and here and (
                    catalog == "pg_default_acl" or (catalog == "pg_proc" and signature in DEFINER_ALLOW_LIST)):
                continue
            found.append(f"role_owns:{role}:{catalog}" + (f":{signature}" if here and signature else ""))

    # Effective CREATE (PUBLIC and inherited grants included) on both CARVIS schemas and the database.
    for role in CHECKED_ROLES:
        for schema in schemas:
            if _rows(connection, "SELECT 1 WHERE pg_catalog.has_schema_privilege(:r, :s, 'CREATE')", r=role, s=schema):
                found.append(f"role_create:{role}:{schema}")
        if _rows(connection, "SELECT 1 WHERE pg_catalog.has_database_privilege(:r, "
                             "pg_catalog.current_database(), 'CREATE')", r=role):
            found.append(f"role_create:{role}:database")

    # Grant options held by a checked role on anything in the CARVIS schemas or on the database.
    option_queries = {
        "database": "SELECT d.datname FROM pg_catalog.pg_database d, pg_catalog.aclexplode(d.datacl) a "
                    "WHERE d.datname = pg_catalog.current_database() AND a.grantee = :g AND a.is_grantable",
        "schema": "SELECT n.nspname FROM pg_catalog.pg_namespace n, pg_catalog.aclexplode(n.nspacl) a "
                  "WHERE n.nspname = ANY(:schemas) AND a.grantee = :g AND a.is_grantable",
        "relation": "SELECT n.nspname || '.' || c.relname FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace, pg_catalog.aclexplode(c.relacl) a "
                    "WHERE n.nspname = ANY(:schemas) AND a.grantee = :g AND a.is_grantable",
        "column": "SELECT n.nspname || '.' || c.relname || '.' || t.attname FROM pg_catalog.pg_attribute t "
                  "JOIN pg_catalog.pg_class c ON c.oid = t.attrelid JOIN pg_catalog.pg_namespace n "
                  "ON n.oid = c.relnamespace, pg_catalog.aclexplode(t.attacl) a "
                  "WHERE n.nspname = ANY(:schemas) AND a.grantee = :g AND a.is_grantable",
        "routine": f"SELECT {SIGNATURE} FROM pg_catalog.pg_proc p "
                   "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace, pg_catalog.aclexplode(p.proacl) a "
                   "WHERE n.nspname = ANY(:schemas) AND a.grantee = :g AND a.is_grantable",
        "type": "SELECT n.nspname || '.' || t.typname FROM pg_catalog.pg_type t "
                "JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace, pg_catalog.aclexplode(t.typacl) a "
                "WHERE n.nspname = ANY(:schemas) AND a.grantee = :g AND a.is_grantable",
    }
    for role in CHECKED_ROLES:
        oid = _rows(connection, "SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :r", r=role)
        if not oid:
            continue
        for kind, sql in option_queries.items():
            for (name,) in _rows(connection, sql, g=oid[0][0], schemas=schemas):
                found.append(f"grant_option:{kind}:{role}:{name}")

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
        "routine": f"SELECT {SIGNATURE} FROM pg_catalog.pg_proc p "
                   "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace, pg_catalog.aclexplode(p.proacl) a "
                   f"WHERE n.nspname = ANY(:schemas) AND a.grantee IN {grantees}",
        "type": "SELECT n.nspname || '.' || t.typname FROM pg_catalog.pg_type t "
                "JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace, pg_catalog.aclexplode(t.typacl) a "
                f"WHERE n.nspname = ANY(:schemas) AND a.grantee IN {grantees}",
        "routine_null_acl": f"SELECT {SIGNATURE} FROM pg_catalog.pg_proc p "
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
    for signature, config, owner, owner_super, acl in _rows(connection, f"""
            SELECT {SIGNATURE}, p.proconfig, r.rolname, r.rolsuper,
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
    # Allow-listed definers must stay SECURITY DEFINER and owned by a definer owner, and must exist
    # whenever the identity tables do (the provisioning path depends on them).
    allow_listed = {row[0]: row[1:] for row in _rows(connection, f"""
            SELECT {SIGNATURE}, p.prosecdef, r.rolname
            FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_catalog.pg_roles r ON r.oid = p.proowner WHERE n.nspname = ANY(:schemas)""", schemas=schemas)
                    if row[0] in DEFINER_ALLOW_LIST}
    tables_present = bool(_rows(connection, """
            SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relname = ANY(:tables)""", schema=SCHEMA, tables=list(IDENTITY_TABLES)))
    for signature in DEFINER_ALLOW_LIST:
        if signature not in allow_listed:
            if tables_present:
                found.append(f"definer_missing:{signature}")
            continue
        secdef, owner = allow_listed[signature]
        if not secdef:
            found.append(f"definer_not_definer:{signature}")
        if owner not in DEFINER_OWNERS:
            found.append(f"definer_owner:{signature}")
    for signature, expected in EXACT_ROUTINE_ACLS.items():
        # Matched through the catalog (to_regprocedure needs USAGE on the schema).
        rows = _rows(connection, "SELECT ARRAY(SELECT pg_catalog.unnest(p.proacl)::text ORDER BY 1) "
                                 "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
                                 f"WHERE n.nspname = ANY(:schemas) AND {SIGNATURE} = :s",
                     s=signature, schemas=schemas)
        if rows and set(rows[0][0] or []) != expected:
            found.append(f"routine_acl:{signature}")

    # Definer owners: only the migration login's ADMIN-only member.
    for role in DEFINER_OWNERS:
        members = _rows(connection, """
                SELECT mr.rolname, m.admin_option, m.inherit_option, m.set_option
                FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r ON r.oid = m.roleid
                JOIN pg_catalog.pg_roles mr ON mr.oid = m.member WHERE r.rolname = :r""", r=role)
        # Doc 04: the sole permanent member is the migration login's PostgreSQL 16 automatic grant,
        # which is ADMIN-only. Any other member, or any other option, could grant itself SET on the
        # definer owner.
        if len(members) > 1:
            found.append(f"definer_owner_members:{role}")
        for member, admin, inherit, can_set in members:
            if member != migration_login or inherit or can_set or not admin:
                found.append(f"definer_owner_member:{role}:{member}")

    # Exact privileges on the identity tables.
    present = {row[0] for row in _rows(connection, """
            SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relname = ANY(:tables) AND c.relkind = 'r'""",
                                       schema=SCHEMA, tables=list(IDENTITY_TABLES))}
    for table in sorted(present):
        held: dict[str, set[tuple[str, str]]] = {}
        for grantee, privilege, column, grantable in _rows(connection, """
                SELECT r.rolname, a.privilege_type, '', a.is_grantable FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace, pg_catalog.aclexplode(c.relacl) a
                JOIN pg_catalog.pg_roles r ON r.oid = a.grantee
                WHERE n.nspname = :schema AND c.relname = :t
                UNION ALL
                SELECT r.rolname, a.privilege_type, t.attname, a.is_grantable FROM pg_catalog.pg_attribute t
                JOIN pg_catalog.pg_class c ON c.oid = t.attrelid JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace, pg_catalog.aclexplode(t.attacl) a
                JOIN pg_catalog.pg_roles r ON r.oid = a.grantee
                WHERE n.nspname = :schema AND c.relname = :t""", schema=SCHEMA, t=table):
            if grantee == OWNER_ROLE:
                continue
            # A grant option is extra authority: it never matches the (non-grantable) allow-list.
            held.setdefault(grantee, set()).add((f"{privilege} WITH GRANT OPTION" if grantable else privilege, column))
        for role in set(held) | {r for r, t in EXACT_TABLE_PRIVILEGES if t == table}:
            if held.get(role, set()) != EXACT_TABLE_PRIVILEGES.get((role, table), set()):
                found.append(f"table_privileges:{role}:{table}")
    return sorted(set(found))
