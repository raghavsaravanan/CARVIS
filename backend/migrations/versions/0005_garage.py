"""Garage persistence: vehicles and immutable vehicle snapshots with forced RLS (M2 B3a).

Specification: ``docs/architecture/03-data-model.md`` (field dictionary, "Immutability rules", "Vehicle context
rules"), ``04-identity-tenancy-rls.md`` (tenant policy shape, "Function privileges"), ADR-0001 and ADR-0003.

**The confirm transaction is an INSERT into ``vehicle_snapshots``.** A caller supplies only ``(vehicle_id,
vehicle_version)`` (column grants). The ``BEFORE INSERT`` trigger ``vehicle_snapshots_confirm`` then:

1. requires a verified principal in ``app.user_id`` (set by ``db/context.py`` from the verified JWT);
2. locks the vehicle ``FOR SHARE`` *as the invoking role*, so row-level security applies: a vehicle outside the
   caller's workspaces is refused exactly like a nonexistent one (before any foreign-key check, which would bypass
   RLS), and a concurrent edit or archive waits for, or is seen by, the confirmation;
3. refuses an archived vehicle and a vehicle not at the supplied version;
4. overwrites every other column from the locked row and the context (``id``, ``workspace_id``, ``config``,
   ``config_hash``, ``source``, ``schema_version``, ``confirmed_by``, ``confirmed_at``).

The trigger fires for every DML insert path (``INSERT``, ``MERGE``) and every role, so no DML produces a snapshot that
is not derived from a current, non-archived vehicle the inserting role can see. ``COPY FROM`` is refused outright by
PostgreSQL for a role subject to row-level security (``carvis_app``, ``carvis_worker``). Roles with DDL
authority over the table (its owner, a superuser) can disable triggers; they are migration and operator
authority, outside the runtime boundary. Every confirmation creates its own snapshot (its own ``confirmed_by`` and
``confirmed_at``); retries of one request are deduplicated by the API's ``Idempotency-Key`` (B3b).

Snapshots are immutable: ``UPDATE``/``DELETE`` row triggers and a ``TRUNCATE`` statement trigger refuse for every
role, and no role is granted those privileges. ``vehicles_guard`` makes every vehicle update increment
``version`` exactly once, makes archiving terminal (owner decision: restoring an archived vehicle is a future,
separately approved contract change) and keeps identity columns fixed.

Variant attributes have three states (doc 03): a value is *known*; ``NULL`` with the name in ``not_applicable`` is
*not applicable*; ``NULL`` otherwise is *unknown*. VINs are unique per workspace, archived vehicles included
(owner decision, 2026-11-24); the check digit is validated in the application (``garage.vin``).

No ``SECURITY DEFINER`` function and no role is added. ``carvis_app`` gains ``EXECUTE`` on ``carvis.uuid_v7()``
because it now inserts rows whose ``id`` defaults to it (doc 04).

Downgrade refuses (fails closed) while either table has rows, counted as ``carvis_owner`` with forced RLS lifted
inside the transaction, as in 0004.

Test hook: forced failures are honored only when ``CARVIS_ENV`` is ``local``.

Revision ID: 0005_garage
Revises: 0004_identity
Create Date: 2026-11-24
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

from db.roles import APP_ROLE, ISSUER_ROLES, METADATA_SCHEMA, SCHEMA, WORKER_ROLE, as_owner

revision = "0005_garage"
down_revision = "0004_identity"
branch_labels = None
depends_on = None

S = SCHEMA
TABLES = ("vehicles", "vehicle_snapshots")
ROUTINES = ("vehicles_guard()", "vehicle_snapshots_confirm()", "vehicle_snapshots_immutable()")
FAIL_STEPS = ("tables", "triggers", "policies", "downgrade_drop")
# Variant attributes, in config order. Each has three states (known / not applicable / unknown).
ATTRIBUTES = ("trim", "engine", "transmission", "drivetrain", "wheel_size", "market", "production_date",
              "production_plant")
SCHEMA_VERSION = 1
# Explicit character list, no bracket ranges (POSIX ranges can be collation dependent): 0-9 and A-Z without I, O, Q.
VIN_CHARACTERS = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"
WORKSPACES = f"nullif(pg_catalog.current_setting('app.workspace_ids', true), '')::pg_catalog.uuid[]"
TENANT = f"workspace_id = ANY({WORKSPACES})"
VEHICLE_INSERT_COLUMNS = ("workspace_id", "vin", "year", "make", "model", *ATTRIBUTES, "not_applicable", "source")
VEHICLE_UPDATE_COLUMNS = ("vin", "year", "make", "model", *ATTRIBUTES, "not_applicable", "archived_at")
SNAPSHOT_INSERT_COLUMNS = ("vehicle_id", "vehicle_version")


class GarageMigrationError(RuntimeError):
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
        raise GarageMigrationError(f"forced failure at {step} (test hook)")


def _login() -> str:
    return _scalar("SELECT current_user")


def _issuer_roles() -> list[str]:
    return [r["rolname"] for r in _rows("SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(:r) ORDER BY 1",
                                        r=list(ISSUER_ROLES))]


def _revoke_public_and_issuers(statement: str) -> None:
    """``statement`` contains ``{grantee}``; applied to PUBLIC and each existing issuer role."""
    for grantee in ("PUBLIC", *_issuer_roles()):
        _exec(statement.format(grantee=grantee))


# --- Preflight ----------------------------------------------------------------------------------

def _preflight() -> None:
    if _scalar(f"SELECT version_num FROM {METADATA_SCHEMA}.alembic_version") != down_revision:
        raise GarageMigrationError("Revision 0004_identity must be the current revision.")
    # Catalog joins, not to_regclass/to_regprocedure: those need USAGE on the schema, which the
    # migration login deliberately lacks.
    for name in TABLES:
        if _scalar("SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                   "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :n", s=S, n=name):
            raise GarageMigrationError(f"{S}.{name} already exists; refusing to adopt it.")
        if _scalar("SELECT count(*) FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n "
                   "ON n.oid = t.typnamespace WHERE n.nspname = :s AND t.typname = :n", s=S, n=name):
            raise GarageMigrationError(f"A type named {S}.{name} already exists; refusing to adopt it.")
    for routine in ROUTINES:
        if _scalar("SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                   "ON n.oid = p.pronamespace WHERE n.nspname = :s AND p.proname = :n",
                   s=S, n=routine.split("(")[0]):
            raise GarageMigrationError(f"{S}.{routine} already exists; refusing to adopt it.")


# --- Objects owned by carvis_owner ------------------------------------------------------------------

def _attribute_columns() -> str:
    columns = []
    for name in ATTRIBUTES:
        if name == "production_date":
            check = f"{name} ~ '^[0-9]{{4}}-(0[1-9]|1[0-2])$'"
        else:
            check = f"char_length({name}) BETWEEN 1 AND 100"
        columns.append(f"{name} text NULL CONSTRAINT vehicles_{name}_value CHECK ({check})")
    return ",\n        ".join(columns)


def _attribute_array() -> str:
    return "ARRAY[" + ", ".join(f"'{name}'" for name in ATTRIBUTES) + "]::text[]"


def _value_or_not_applicable() -> str:
    return " AND ".join(f"NOT ({name} IS NOT NULL AND '{name}' = ANY (not_applicable))" for name in ATTRIBUTES)


TABLE_DDL = [
    f"""CREATE TABLE {S}.vehicles (
        id uuid PRIMARY KEY DEFAULT {S}.uuid_v7(),
        workspace_id uuid NOT NULL REFERENCES {S}.workspaces (id) ON DELETE RESTRICT,
        vin text NULL CONSTRAINT vehicles_vin_format CHECK (vin ~ '^[{VIN_CHARACTERS}]{{17}}$'),
        year smallint NOT NULL CONSTRAINT vehicles_year_range CHECK (year BETWEEN 1900 AND 2100),
        make text NOT NULL CONSTRAINT vehicles_make_value CHECK (char_length(make) BETWEEN 1 AND 64),
        model text NOT NULL CONSTRAINT vehicles_model_value CHECK (char_length(model) BETWEEN 1 AND 64),
        {_attribute_columns()},
        not_applicable text[] NOT NULL DEFAULT '{{}}' CONSTRAINT vehicles_not_applicable_known
            CHECK (not_applicable <@ {_attribute_array()} AND array_position(not_applicable, NULL) IS NULL),
        source text NOT NULL DEFAULT 'manual' CONSTRAINT vehicles_source_value
            CHECK (source IN ('manual', 'vin_decode')),
        archived_at timestamptz NULL,
        version integer NOT NULL DEFAULT 1 CONSTRAINT vehicles_version_positive CHECK (version >= 1),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT vehicles_workspace_id_id_key UNIQUE (workspace_id, id),
        CONSTRAINT vehicles_workspace_vin_key UNIQUE (workspace_id, vin),
        CONSTRAINT vehicles_value_or_not_applicable CHECK ({_value_or_not_applicable()}))""",
    f"CREATE INDEX vehicles_workspace_archived_idx ON {S}.vehicles (workspace_id, archived_at)",
    f"""CREATE TABLE {S}.vehicle_snapshots (
        id uuid PRIMARY KEY DEFAULT {S}.uuid_v7(),
        workspace_id uuid NOT NULL,
        vehicle_id uuid NOT NULL,
        vehicle_version integer NOT NULL CONSTRAINT vehicle_snapshots_version_positive CHECK (vehicle_version >= 1),
        schema_version smallint NOT NULL CONSTRAINT vehicle_snapshots_schema_version
            CHECK (schema_version = {SCHEMA_VERSION}),
        config jsonb NOT NULL CONSTRAINT vehicle_snapshots_config_shape
            CHECK (jsonb_typeof(config) = 'object' AND config -> 'schema_version' = to_jsonb(schema_version)),
        config_hash text NOT NULL CONSTRAINT vehicle_snapshots_config_hash_format
            CHECK (config_hash ~ '^[0123456789abcdef]{{64}}$'),
        source text NOT NULL CONSTRAINT vehicle_snapshots_source_value CHECK (source IN ('manual', 'vin_decode')),
        confirmed_by uuid NOT NULL REFERENCES {S}.users (id) ON DELETE RESTRICT,
        confirmed_at timestamptz NOT NULL,
        CONSTRAINT vehicle_snapshots_vehicle_fk FOREIGN KEY (workspace_id, vehicle_id)
            REFERENCES {S}.vehicles (workspace_id, id) ON DELETE RESTRICT,
        CONSTRAINT vehicle_snapshots_workspace_id_id_key UNIQUE (workspace_id, id))""",
    f"CREATE INDEX vehicle_snapshots_vehicle_idx ON {S}.vehicle_snapshots (workspace_id, vehicle_id, confirmed_at)",
]

VEHICLES_GUARD = f"""
CREATE FUNCTION {S}.vehicles_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  IF OLD.archived_at IS NOT NULL THEN
    RAISE EXCEPTION USING ERRCODE = '55000', CONSTRAINT = 'vehicles_archived_is_terminal',
      MESSAGE = 'vehicle refused: an archived vehicle cannot be changed';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
     OR NEW.source IS DISTINCT FROM OLD.source OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'vehicles_identity_immutable',
      MESSAGE = 'vehicle refused: identity columns are immutable';
  END IF;
  -- Every update, archiving included, is exactly one new version; the caller's values are ignored.
  NEW.version := OLD.version + 1;
  NEW.updated_at := pg_catalog.now();
  IF NEW.archived_at IS NOT NULL THEN
    NEW.archived_at := pg_catalog.now();
  END IF;
  RETURN NEW;
END
$fn$"""

SNAPSHOT_CONFIRM = f"""
CREATE FUNCTION {S}.vehicle_snapshots_confirm() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_user pg_catalog.uuid;
  v {S}.vehicles%ROWTYPE;
  v_row pg_catalog.jsonb;
  v_attributes pg_catalog.jsonb := '{{}}'::pg_catalog.jsonb;
  v_name pg_catalog.text;
  v_config pg_catalog.jsonb;
BEGIN
  -- 1. The verified principal (doc 04 tenant context); none means no confirmation.
  v_user := nullif(pg_catalog.current_setting('app.user_id', true), '')::pg_catalog.uuid;
  IF v_user IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '42501', CONSTRAINT = 'vehicle_snapshots_confirmed_by_context',
      MESSAGE = 'snapshot refused: no verified principal';
  END IF;
  -- 2. Lock the vehicle as the invoking role: RLS applies, so another workspace's vehicle is not found, exactly
  --    like a nonexistent one, before any foreign-key check (which would bypass RLS).
  SELECT x.* INTO v FROM {S}.vehicles AS x WHERE x.id = NEW.vehicle_id FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION USING ERRCODE = '23503', CONSTRAINT = 'vehicle_snapshots_vehicle_visible',
      MESSAGE = 'snapshot refused: vehicle not found';
  END IF;
  -- 3. Only a non-archived vehicle at the version the technician saw.
  IF v.archived_at IS NOT NULL THEN
    RAISE EXCEPTION USING ERRCODE = '55000', CONSTRAINT = 'vehicle_snapshots_vehicle_not_archived',
      MESSAGE = 'snapshot refused: vehicle is archived';
  END IF;
  IF NEW.vehicle_version IS NULL OR v.version <> NEW.vehicle_version THEN
    RAISE EXCEPTION USING ERRCODE = '55000', CONSTRAINT = 'vehicle_snapshots_current_version',
      MESSAGE = 'snapshot refused: vehicle version is not current';
  END IF;
  -- 4. Derive everything else from the locked row and the context.
  v_row := pg_catalog.to_jsonb(v);
  FOREACH v_name IN ARRAY {_attribute_array().replace('::text[]', '::pg_catalog.text[]')} LOOP
    IF v_row ->> v_name IS NOT NULL THEN
      v_attributes := v_attributes || pg_catalog.jsonb_build_object(
        v_name, pg_catalog.jsonb_build_object('state', 'known', 'value', v_row -> v_name));
    ELSIF v_name = ANY (v.not_applicable) THEN
      v_attributes := v_attributes || pg_catalog.jsonb_build_object(
        v_name, pg_catalog.jsonb_build_object('state', 'not_applicable'));
    ELSE
      v_attributes := v_attributes || pg_catalog.jsonb_build_object(
        v_name, pg_catalog.jsonb_build_object('state', 'unknown'));
    END IF;
  END LOOP;
  v_config := pg_catalog.jsonb_build_object('schema_version', {SCHEMA_VERSION}, 'vin', v.vin, 'year', v.year,
                                            'make', v.make, 'model', v.model, 'attributes', v_attributes);
  NEW.id := {S}.uuid_v7();
  NEW.workspace_id := v.workspace_id;
  NEW.vehicle_version := v.version;
  NEW.schema_version := {SCHEMA_VERSION};
  NEW.config := v_config;
  NEW.config_hash := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(v_config::pg_catalog.text, 'UTF8')),
                                       'hex');
  NEW.source := v.source;
  NEW.confirmed_by := v_user;
  NEW.confirmed_at := pg_catalog.now();
  RETURN NEW;
END
$fn$"""

SNAPSHOT_IMMUTABLE = f"""
CREATE FUNCTION {S}.vehicle_snapshots_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  RAISE EXCEPTION USING ERRCODE = '55000', CONSTRAINT = 'vehicle_snapshots_immutable',
    MESSAGE = 'vehicle snapshots are immutable';
END
$fn$"""

TRIGGERS = [
    VEHICLES_GUARD,
    f"CREATE TRIGGER vehicles_guard BEFORE UPDATE ON {S}.vehicles FOR EACH ROW EXECUTE FUNCTION {S}.vehicles_guard()",
    SNAPSHOT_CONFIRM,
    f"""CREATE TRIGGER vehicle_snapshots_confirm BEFORE INSERT ON {S}.vehicle_snapshots
        FOR EACH ROW EXECUTE FUNCTION {S}.vehicle_snapshots_confirm()""",
    SNAPSHOT_IMMUTABLE,
    f"""CREATE TRIGGER vehicle_snapshots_immutable BEFORE UPDATE OR DELETE ON {S}.vehicle_snapshots
        FOR EACH ROW EXECUTE FUNCTION {S}.vehicle_snapshots_immutable()""",
    f"""CREATE TRIGGER vehicle_snapshots_no_truncate BEFORE TRUNCATE ON {S}.vehicle_snapshots
        FOR EACH STATEMENT EXECUTE FUNCTION {S}.vehicle_snapshots_immutable()""",
]

POLICIES = [
    f"CREATE POLICY vehicles_tenant_read ON {S}.vehicles FOR SELECT TO {APP_ROLE}, {WORKER_ROLE} USING ({TENANT})",
    f"CREATE POLICY vehicles_tenant_insert ON {S}.vehicles FOR INSERT TO {APP_ROLE} WITH CHECK ({TENANT})",
    f"CREATE POLICY vehicles_tenant_update ON {S}.vehicles FOR UPDATE TO {APP_ROLE} USING ({TENANT}) "
    f"WITH CHECK ({TENANT})",
    f"CREATE POLICY vehicle_snapshots_tenant_read ON {S}.vehicle_snapshots FOR SELECT TO {APP_ROLE}, {WORKER_ROLE} "
    f"USING ({TENANT})",
    f"CREATE POLICY vehicle_snapshots_tenant_insert ON {S}.vehicle_snapshots FOR INSERT TO {APP_ROLE} "
    f"WITH CHECK ({TENANT})",
]

GRANTS = [
    *(f"GRANT SELECT ON {S}.{t} TO {APP_ROLE}, {WORKER_ROLE}" for t in TABLES),
    f"GRANT INSERT ({', '.join(VEHICLE_INSERT_COLUMNS)}) ON {S}.vehicles TO {APP_ROLE}",
    f"GRANT UPDATE ({', '.join(VEHICLE_UPDATE_COLUMNS)}) ON {S}.vehicles TO {APP_ROLE}",
    f"GRANT INSERT ({', '.join(SNAPSHOT_INSERT_COLUMNS)}) ON {S}.vehicle_snapshots TO {APP_ROLE}",
    f"GRANT EXECUTE ON FUNCTION {S}.uuid_v7() TO {APP_ROLE}",
]


def upgrade() -> None:
    _preflight()
    with as_owner(op.get_bind()):
        for statement in TABLE_DDL:
            _exec(statement)
        _maybe_fail("tables")
        for statement in TRIGGERS:
            _exec(statement)
        for routine in ROUTINES:
            _revoke_public_and_issuers(f"REVOKE ALL ON FUNCTION {S}.{routine} FROM {{grantee}}")
        _maybe_fail("triggers")
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
    _postconditions()


def _postconditions() -> None:
    from db.catalog import violations

    found = violations(op.get_bind(), migration_login=_login())
    if found:
        raise GarageMigrationError("Catalog check failed: " + ", ".join(found))


def _garage_rows() -> int:
    """Rows in the garage tables, counted as carvis_owner with forced RLS lifted for this transaction only."""
    total = 0
    with as_owner(op.get_bind()):
        for table in TABLES:
            _exec(f"ALTER TABLE {S}.{table} NO FORCE ROW LEVEL SECURITY")
            total += _scalar(f"SELECT count(*) FROM {S}.{table}")
            _exec(f"ALTER TABLE {S}.{table} FORCE ROW LEVEL SECURITY")
    return total


def downgrade() -> None:
    if _garage_rows():
        raise GarageMigrationError("Garage tables contain rows; refusing to drop them (doc 08: no "
                                   "data-destroying DDL without a preflight and a verified backup).")
    with as_owner(op.get_bind()):
        _exec(f"REVOKE EXECUTE ON FUNCTION {S}.uuid_v7() FROM {APP_ROLE}")
        _maybe_fail("downgrade_drop")
        for table in reversed(TABLES):
            _exec(f"DROP TABLE {S}.{table}")
        for routine in reversed(ROUTINES):
            _exec(f"DROP FUNCTION {S}.{routine}")
    _postconditions()
