"""Identity tables with forced RLS, the UUID v7 helper, and ensure_principal provisioning (M2 B2b-1).

Specification: ``docs/architecture/04-identity-tenancy-rls.md`` ("Roles", "Function privileges",
"Function ownership and migration membership", "Context carrier" policy shapes, "Provisioning");
``03-data-model.md``; ADR-0003.

Upgrade, in this revision's single transaction (any failure rolls everything back):

1. Preflight (fail closed, before any change): 0003 applied; ``carvis_provisioner`` and
   ``carvis_bootstrap`` NOLOGIN with no elevated attribute and members of no role;
   ``carvis_provisioner`` has no member except the migration login's ADMIN-only grant; none of this
   revision's objects exists yet.
2. As ``carvis_owner``: ``carvis.uuid_v7()``; ``users``, ``workspaces``, ``memberships``; the two
   invoker trigger functions and their triggers; RLS enabled and forced; the policies; the grants;
   every revoke from ``PUBLIC`` and the issuer roles (tables, row types, routines).
3. ``carvis.ensure_principal`` created as ``carvis_provisioner`` under the temporary-membership
   procedure (temporary ``INHERIT FALSE, SET TRUE`` grant to a non-superuser login, temporary
   ``CREATE`` on ``carvis``, both revoked before commit); ``EXECUTE`` only for ``carvis_bootstrap``.
4. Post-condition: :func:`db.catalog.violations` is empty.

Workspace ownership (owner decision, 2026-11-24): the owner-presence trigger is deferred. In B2b-1 no
runtime role can create a shop workspace or UPDATE/DELETE a membership or workspace, and personal
workspaces are created only by ``ensure_principal`` together with their owner membership. The trigger
is mandatory in the first package that adds shop-workspace creation or membership UPDATE/DELETE.

Downgrade refuses (fails closed) while any identity table has rows, counting them as
``carvis_owner`` with forced RLS lifted inside the transaction (forced RLS would otherwise hide every
row from the owner). It then drops the function (as ``carvis_provisioner``, under the same temporary
membership), the tables and the helpers, and checks the definer owner again.

Test hook: as in 0003, forced failures are honored only when ``CARVIS_ENV`` is ``local``.

Revision ID: 0004_identity
Revises: 0003_runtime_roles
Create Date: 2026-11-24
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from alembic import op
from sqlalchemy import text

from db.roles import (APP_ROLE, BOOTSTRAP_ROLE, ISSUER_ROLES, METADATA_SCHEMA, OWNER_ROLE, PROVISIONER_ROLE, SCHEMA,
                      WORKER_ROLE, as_owner, as_role)

revision = "0004_identity"
down_revision = "0003_runtime_roles"
branch_labels = None
depends_on = None

TABLES = ("users", "workspaces", "memberships")
OWNER_ROUTINES = ("uuid_v7()", "memberships_personal_owner_check()", "workspaces_owner_immutable()")
DEFINER = "ensure_principal(text,text,text)"
ELEVATED = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls", "rolcanlogin")
FAIL_STEPS = ("tables", "policies", "temporary_grant", "definer", "downgrade_drop")
S = SCHEMA
SETTING = "nullif(pg_catalog.current_setting('{name}', true), '')"
USER_ID = SETTING.format(name="app.user_id") + "::uuid"
WORKSPACE_IDS = SETTING.format(name="app.workspace_ids") + "::uuid[]"
BOOT_ISSUER = SETTING.format(name="app.bootstrap_issuer")
BOOT_SUBJECT = SETTING.format(name="app.bootstrap_subject")
BOOT_USER_ID = SETTING.format(name="app.bootstrap_user_id") + "::uuid"


class IdentityMigrationError(RuntimeError):
    """The database cannot take this revision safely. Names objects and conditions only."""


def _scalar(sql: str, **params):
    return op.get_bind().execute(text(sql), params).scalar()


def _rows(sql: str, **params):
    return op.get_bind().execute(text(sql), params).mappings().all()


def _exec(sql: str) -> None:
    op.get_bind().execute(text(sql))


def _maybe_fail(step: str) -> None:
    from webhook_auth import LOCAL, deployment_environment

    if deployment_environment() == LOCAL and os.getenv("CARVIS_TEST_FAIL_AT") == step:
        raise IdentityMigrationError(f"forced failure at {step} (test hook)")


def _login() -> tuple[str, bool]:
    row = _rows("SELECT rolname, rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user")[0]
    return row["rolname"], row["rolsuper"]


def _issuer_roles() -> list[str]:
    return [r["rolname"] for r in _rows("SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(:r) ORDER BY 1",
                                        r=list(ISSUER_ROLES))]


@contextmanager
def _with_temporary_set(role: str, superuser: bool) -> Iterator[None]:
    """Temporary ``WITH INHERIT FALSE, SET TRUE`` membership for a non-superuser login (doc 04)."""
    if not superuser:
        _exec(f"GRANT {role} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE")
    with as_role(op.get_bind(), role):
        yield
    _maybe_fail("temporary_grant")
    # Revoked only after success; on failure the transaction rollback removes the grant too.
    if not superuser:
        _exec(f"REVOKE {role} FROM CURRENT_USER GRANTED BY CURRENT_USER")


# --- Preflight ----------------------------------------------------------------------------------

def _preflight(login: str) -> None:
    if _scalar(f"SELECT version_num FROM {METADATA_SCHEMA}.alembic_version") != down_revision:
        raise IdentityMigrationError("Revision 0003_runtime_roles must be the current revision.")
    for role in (PROVISIONER_ROLE, BOOTSTRAP_ROLE):
        attributes = _rows(f"SELECT {', '.join(ELEVATED)} FROM pg_catalog.pg_roles WHERE rolname = :r", r=role)
        if not attributes or any(attributes[0][name] for name in ELEVATED):
            raise IdentityMigrationError(f"Role {role} is missing or has LOGIN or an elevated attribute.")
        if _scalar("SELECT count(*) FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r "
                   "ON r.oid = m.member WHERE r.rolname = :r", r=role):
            raise IdentityMigrationError(f"Role {role} is a member of another role.")
    for member in _rows("""SELECT mr.rolname AS member, m.admin_option, m.inherit_option, m.set_option
                           FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r ON r.oid = m.roleid
                           JOIN pg_catalog.pg_roles mr ON mr.oid = m.member WHERE r.rolname = :r""",
                        r=PROVISIONER_ROLE):
        if member["member"] != login or not member["admin_option"] or member["inherit_option"] \
                or member["set_option"]:
            raise IdentityMigrationError(f"Role {PROVISIONER_ROLE} has a member other than the migration "
                                         "login's ADMIN-only grant.")
    # Catalog joins, not to_regclass/to_regprocedure: those need USAGE on the schema, which the
    # migration login deliberately lacks.
    for name in TABLES:
        if _scalar("SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                   "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :n", s=S, n=name):
            raise IdentityMigrationError(f"{S}.{name} already exists; refusing to adopt it.")
    for routine in (*OWNER_ROUTINES, DEFINER):
        if _scalar("SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                   "ON n.oid = p.pronamespace WHERE n.nspname = :s AND p.proname = :n",
                   s=S, n=routine.split("(")[0]):
            raise IdentityMigrationError(f"{S}.{routine} already exists; refusing to adopt it.")


# --- Objects owned by carvis_owner ------------------------------------------------------------------

UUID_V7 = f"""
CREATE FUNCTION {S}.uuid_v7() RETURNS uuid
LANGUAGE sql VOLATILE SECURITY INVOKER SET search_path = pg_catalog, pg_temp AS $fn$
  -- RFC 9562 version 7: 48-bit Unix milliseconds, then gen_random_uuid() bits with version 7 (the
  -- version-4 nibble 0100 gains bits 52 and 53 to become 0111); the variant stays 10.
  SELECT encode(set_bit(set_bit(overlay(uuid_send(gen_random_uuid())
           PLACING substring(int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
           FROM 1 FOR 6), 52, 1), 53, 1), 'hex')::uuid
$fn$"""

TABLE_DDL = [
    f"""CREATE TABLE {S}.users (
        id uuid PRIMARY KEY DEFAULT {S}.uuid_v7(),
        auth_issuer text NOT NULL CHECK (char_length(auth_issuer) BETWEEN 1 AND 255),
        auth_subject text NOT NULL CHECK (char_length(auth_subject) BETWEEN 1 AND 255),
        email text NULL CHECK (char_length(email) <= 320),
        display_name text NULL CHECK (char_length(display_name) <= 200),
        status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleting', 'deleted')),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT users_principal_key UNIQUE (auth_issuer, auth_subject))""",
    f"""CREATE TABLE {S}.workspaces (
        id uuid PRIMARY KEY DEFAULT {S}.uuid_v7(),
        kind text NOT NULL CHECK (kind IN ('personal', 'shop')),
        name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
        personal_owner_user_id uuid NULL REFERENCES {S}.users (id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT workspaces_personal_owner_key UNIQUE (personal_owner_user_id),
        CONSTRAINT workspaces_personal_owner_iff_personal
            CHECK ((kind = 'personal') = (personal_owner_user_id IS NOT NULL)))""",
    f"""CREATE TABLE {S}.memberships (
        workspace_id uuid NOT NULL REFERENCES {S}.workspaces (id) ON DELETE RESTRICT,
        user_id uuid NOT NULL REFERENCES {S}.users (id) ON DELETE RESTRICT,
        role text NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (workspace_id, user_id))""",
    f"CREATE INDEX memberships_user_id_idx ON {S}.memberships (user_id)",
]

TRIGGERS = [
    f"""CREATE FUNCTION {S}.memberships_personal_owner_check() RETURNS trigger
    LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, pg_temp AS $fn$
    DECLARE
      v_kind text;
      v_owner uuid;
    BEGIN
      -- Runs as the inserting role, so the lookup is subject to that role's RLS: a workspace it
      -- cannot see is refused (fail closed).
      SELECT w.kind, w.personal_owner_user_id INTO v_kind, v_owner
        FROM {S}.workspaces w WHERE w.id = NEW.workspace_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'membership refused: workspace not visible';
      END IF;
      IF v_kind = 'personal' AND (NEW.user_id IS DISTINCT FROM v_owner OR NEW.role <> 'owner') THEN
        RAISE EXCEPTION USING ERRCODE = '23514',
          MESSAGE = 'membership refused: a personal workspace has only its owner, as owner';
      END IF;
      RETURN NULL;
    END
    $fn$""",
    f"""CREATE CONSTRAINT TRIGGER memberships_personal_owner_check
        AFTER INSERT OR UPDATE ON {S}.memberships NOT DEFERRABLE
        FOR EACH ROW EXECUTE FUNCTION {S}.memberships_personal_owner_check()""",
    f"""CREATE FUNCTION {S}.workspaces_owner_immutable() RETURNS trigger
    LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, pg_temp AS $fn$
    BEGIN
      IF NEW.kind IS DISTINCT FROM OLD.kind
         OR NEW.personal_owner_user_id IS DISTINCT FROM OLD.personal_owner_user_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'workspace kind and personal owner are immutable';
      END IF;
      RETURN NEW;
    END
    $fn$""",
    f"""CREATE TRIGGER workspaces_owner_immutable BEFORE UPDATE ON {S}.workspaces
        FOR EACH ROW EXECUTE FUNCTION {S}.workspaces_owner_immutable()""",
]

POLICIES = [
    f"CREATE POLICY users_self ON {S}.users FOR SELECT TO {APP_ROLE}, {WORKER_ROLE} USING (id = {USER_ID})",
    f"CREATE POLICY users_provision_read ON {S}.users FOR SELECT TO {PROVISIONER_ROLE} "
    f"USING (auth_issuer = {BOOT_ISSUER} AND auth_subject = {BOOT_SUBJECT})",
    f"CREATE POLICY users_provision_insert ON {S}.users FOR INSERT TO {PROVISIONER_ROLE} "
    f"WITH CHECK (auth_issuer = {BOOT_ISSUER} AND auth_subject = {BOOT_SUBJECT})",
    f"CREATE POLICY workspaces_member ON {S}.workspaces FOR SELECT TO {APP_ROLE}, {WORKER_ROLE} "
    f"USING (id = ANY({WORKSPACE_IDS}))",
    f"CREATE POLICY workspaces_provision_read ON {S}.workspaces FOR SELECT TO {PROVISIONER_ROLE} "
    f"USING (kind = 'personal' AND personal_owner_user_id = {BOOT_USER_ID})",
    f"CREATE POLICY workspaces_provision_insert ON {S}.workspaces FOR INSERT TO {PROVISIONER_ROLE} "
    f"WITH CHECK (kind = 'personal' AND personal_owner_user_id = {BOOT_USER_ID})",
    f"CREATE POLICY memberships_self ON {S}.memberships FOR SELECT TO {APP_ROLE}, {WORKER_ROLE} "
    f"USING (user_id = {USER_ID})",
    f"CREATE POLICY memberships_provision_read ON {S}.memberships FOR SELECT TO {PROVISIONER_ROLE} "
    f"USING (user_id = {BOOT_USER_ID})",
    f"CREATE POLICY memberships_provision_insert ON {S}.memberships FOR INSERT TO {PROVISIONER_ROLE} "
    f"WITH CHECK (user_id = {BOOT_USER_ID} AND role = 'owner' AND workspace_id = "
    f"(SELECT w.id FROM {S}.workspaces w WHERE w.kind = 'personal' AND w.personal_owner_user_id = {BOOT_USER_ID}))",
]

GRANTS = [
    *(f"GRANT SELECT ON {S}.{t} TO {APP_ROLE}, {WORKER_ROLE}" for t in TABLES),
    f"GRANT SELECT (id, status, auth_issuer, auth_subject) ON {S}.users TO {PROVISIONER_ROLE}",
    f"GRANT INSERT (auth_issuer, auth_subject, email) ON {S}.users TO {PROVISIONER_ROLE}",
    f"GRANT SELECT (id, kind, personal_owner_user_id) ON {S}.workspaces TO {PROVISIONER_ROLE}",
    f"GRANT INSERT ON {S}.workspaces TO {PROVISIONER_ROLE}",
    f"GRANT SELECT (workspace_id, user_id, role) ON {S}.memberships TO {PROVISIONER_ROLE}",
    f"GRANT INSERT ON {S}.memberships TO {PROVISIONER_ROLE}",
    f"GRANT EXECUTE ON FUNCTION {S}.uuid_v7() TO {PROVISIONER_ROLE}",
]

ENSURE_PRINCIPAL = f"""
CREATE FUNCTION {S}.ensure_principal(p_issuer text, p_subject text, p_email text)
RETURNS TABLE (user_id uuid, status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
#variable_conflict use_column
DECLARE
  v_user_id uuid;
  v_status text;
  v_workspace_id uuid;
BEGIN
  -- Inputs: exact equality only; NULL is refused explicitly (a length check alone lets NULL pass).
  IF p_issuer IS NULL OR p_subject IS NULL
     OR char_length(p_issuer) NOT BETWEEN 1 AND 255 OR char_length(p_subject) NOT BETWEEN 1 AND 255
     OR (p_email IS NOT NULL AND char_length(p_email) > 320) THEN
    RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'invalid principal';
  END IF;
  -- The concurrency design (insert, then a fresh read) relies on READ COMMITTED.
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION USING ERRCODE = '25000', MESSAGE = 'ensure_principal requires READ COMMITTED';
  END IF;

  -- 1. Bind the provisioner policies to this principal, overwriting anything the caller set.
  PERFORM set_config('app.bootstrap_issuer', p_issuer, true);
  PERFORM set_config('app.bootstrap_subject', p_subject, true);
  PERFORM set_config('app.bootstrap_user_id', '', true);

  -- 2. Find or create the user (email only on creation).
  INSERT INTO {S}.users AS u (auth_issuer, auth_subject, email)
    VALUES (p_issuer, p_subject, p_email)
    ON CONFLICT (auth_issuer, auth_subject) DO NOTHING;
  SELECT u.id, u.status INTO v_user_id, v_status
    FROM {S}.users u WHERE u.auth_issuer = p_issuer AND u.auth_subject = p_subject;

  -- 3. A non-active user gets nothing new.
  IF v_status = 'active' THEN
    -- 4. Find or create the personal workspace.
    PERFORM set_config('app.bootstrap_user_id', v_user_id::text, true);
    INSERT INTO {S}.workspaces AS w (kind, name, personal_owner_user_id)
      VALUES ('personal', 'Personal', v_user_id)
      ON CONFLICT (personal_owner_user_id) DO NOTHING;
    SELECT w.id INTO v_workspace_id
      FROM {S}.workspaces w WHERE w.kind = 'personal' AND w.personal_owner_user_id = v_user_id;
    -- 5. Find or create the owner membership.
    INSERT INTO {S}.memberships AS m (workspace_id, user_id, role)
      VALUES (v_workspace_id, v_user_id, 'owner')
      ON CONFLICT (workspace_id, user_id) DO NOTHING;
  END IF;

  -- 6. Clear the bootstrap settings and return only (user_id, status).
  PERFORM set_config('app.bootstrap_issuer', '', true);
  PERFORM set_config('app.bootstrap_subject', '', true);
  PERFORM set_config('app.bootstrap_user_id', '', true);
  user_id := v_user_id;
  status := v_status;
  RETURN NEXT;
END
$fn$"""


def _revoke_public_and_issuers(statement: str) -> None:
    """``statement`` contains ``{grantee}``; applied to PUBLIC and each existing issuer role."""
    for grantee in ("PUBLIC", *_issuer_roles()):
        _exec(statement.format(grantee=grantee))


def upgrade() -> None:
    login, superuser = _login()
    _preflight(login)

    with as_owner(op.get_bind()):
        _exec(UUID_V7)
        _revoke_public_and_issuers(f"REVOKE ALL ON FUNCTION {S}.uuid_v7() FROM {{grantee}}")
        for statement in TABLE_DDL:
            _exec(statement)
        _maybe_fail("tables")
        for statement in TRIGGERS:
            _exec(statement)
        for routine in OWNER_ROUTINES[1:]:
            _revoke_public_and_issuers(f"REVOKE ALL ON FUNCTION {S}.{routine} FROM {{grantee}}")
        for table in TABLES:
            _exec(f"ALTER TABLE {S}.{table} ENABLE ROW LEVEL SECURITY")
            _exec(f"ALTER TABLE {S}.{table} FORCE ROW LEVEL SECURITY")
            _revoke_public_and_issuers(f"REVOKE ALL ON TABLE {S}.{table} FROM {{grantee}}")
            # A table's row type has a NULL ACL, which grants PUBLIC USAGE.
            _revoke_public_and_issuers(f"REVOKE ALL ON TYPE {S}.{table} FROM {{grantee}}")
        for statement in POLICIES:
            _exec(statement)
        for statement in GRANTS:
            _exec(statement)
        _maybe_fail("policies")
        # Temporary CREATE so carvis_provisioner can own a routine in carvis (doc 04, step 3).
        _exec(f"GRANT CREATE ON SCHEMA {S} TO {PROVISIONER_ROLE}")

    with _with_temporary_set(PROVISIONER_ROLE, superuser):
        _exec(ENSURE_PRINCIPAL)
        _revoke_public_and_issuers(f"REVOKE ALL ON FUNCTION {S}.{DEFINER} FROM {{grantee}}")
        _exec(f"GRANT EXECUTE ON FUNCTION {S}.{DEFINER} TO {BOOTSTRAP_ROLE}")
    _maybe_fail("definer")

    with as_owner(op.get_bind()):
        _exec(f"REVOKE CREATE ON SCHEMA {S} FROM {PROVISIONER_ROLE}")

    _postconditions()


def _postconditions() -> None:
    from db.catalog import violations

    # The migration login is the only role allowed to keep the ADMIN-only definer-owner membership.
    found = violations(op.get_bind(), migration_login=_login()[0])
    if found:
        raise IdentityMigrationError("Catalog check failed: " + ", ".join(found))


def _identity_rows() -> int:
    """Rows in the identity tables, counted as carvis_owner with forced RLS lifted for this
    transaction only (forced RLS hides every row from the owner, which has no policy)."""
    total = 0
    with as_owner(op.get_bind()):
        for table in TABLES:
            _exec(f"ALTER TABLE {S}.{table} NO FORCE ROW LEVEL SECURITY")
            total += _scalar(f"SELECT count(*) FROM {S}.{table}")
            _exec(f"ALTER TABLE {S}.{table} FORCE ROW LEVEL SECURITY")
    return total


def downgrade() -> None:
    _, superuser = _login()
    if _identity_rows():
        raise IdentityMigrationError("Identity tables contain rows; refusing to drop them (doc 08: no "
                                     "data-destroying DDL without a preflight and a verified backup).")
    with _with_temporary_set(PROVISIONER_ROLE, superuser):
        _exec(f"DROP FUNCTION {S}.{DEFINER}")
    _maybe_fail("downgrade_drop")
    with as_owner(op.get_bind()):
        for table in reversed(TABLES):
            _exec(f"DROP TABLE {S}.{table}")
        for routine in reversed(OWNER_ROUTINES):
            _exec(f"DROP FUNCTION {S}.{routine}")
    _postconditions()
