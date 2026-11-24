"""M2 B3a: vehicles and immutable vehicle snapshots with forced RLS, on real PostgreSQL 16.

Covers the design's invariants I1–I9 at database level: tenant isolation (doc 04 "Validation" 1, 2, 6, 7 worker
part, 10, 12, 13 for the garage tables), the confirm trigger as the only DML path that creates a snapshot,
immutability (doc 03 "Immutability rules", through the application role and the owner), the vehicle guard, the
catalog rules and the migration round trip. Same server requirements as ``test_b1_migrations.py``.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid

import psycopg
import pytest

from tests.test_b1_migrations import _sql, admin_url, scratch  # noqa: F401
from tests.test_b2a_migrations import migrator, ok, run_alembic  # noqa: F401
from tests.test_b2a_runtime_login import RUNTIME, runtime_login
from tests.test_b2b1_identity import as_role, ensure, identity_catalog, violations

HEAD = "0005_garage"
PREVIOUS = "0004_identity"
ATTRIBUTES = ("trim", "engine", "transmission", "drivetrain", "wheel_size", "market", "production_date",
              "production_plant")
VIN = "1M8GDM9AXKP042788"


# --- fixtures and helpers -------------------------------------------------------------------------

@pytest.fixture
def head(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD))
    return migrator


@pytest.fixture
def login(scratch, head):
    url = scratch.login(RUNTIME)
    assert runtime_login(head, "grant", RUNTIME).returncode == 0
    return url


@pytest.fixture
def people(scratch, login):
    """Users a, b, c with personal workspaces; a shop workspace ``ws`` whose members are a and c."""
    ids = {who: str(ensure(login, f"user-{who}")[1][0]) for who in "abc"}
    out = dict(ids)
    for who in "abc":
        out["w" + who] = str(_sql(scratch.db_admin, "SELECT id FROM carvis.workspaces "
                                                    f"WHERE personal_owner_user_id = '{ids[who]}'", fetch=True)[0][0])
    shop = str(uuid.uuid4())
    _sql(scratch.db_admin, f"INSERT INTO carvis.workspaces (id, kind, name) VALUES ('{shop}', 'shop', 'Shop')",
         f"INSERT INTO carvis.memberships VALUES ('{shop}', '{ids['a']}', 'owner'), ('{shop}', '{ids['c']}', 'member')")
    out["ws"] = shop
    return out


def ctx(p: dict, who: str) -> dict[str, str]:
    workspaces = [p["w" + who]] + ([p["ws"]] if who in "ac" else [])
    return {"app.user_id": p[who], "app.workspace_ids": "{" + ",".join(workspaces) + "}"}


def app(scratch, p, who, statements, fetch=True, role="carvis_app"):
    return as_role(scratch.db_admin, role, statements if isinstance(statements, list) else [statements],
                   ctx(p, who), fetch=fetch)


def add_vehicle(scratch, p, who, workspace=None, vin=None, **columns) -> str:
    values = {"workspace_id": workspace or p["w" + who], "year": 2019, "make": "Ford", "model": "F-150", **columns}
    if vin:
        values["vin"] = vin
    names = ", ".join(values)
    literals = ", ".join("%s" % _literal(v) for v in values.values())
    return str(app(scratch, p, who, f"INSERT INTO carvis.vehicles ({names}) VALUES ({literals}) RETURNING id")[0][0])


def _literal(value) -> str:
    if isinstance(value, (list, tuple)):
        return "ARRAY[" + ",".join(f"'{v}'" for v in value) + "]::text[]" if value else "'{}'::text[]"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def confirm(scratch, p, who, vehicle, version=1):
    rows = app(scratch, p, who, "INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version) "
                                f"VALUES ('{vehicle}', {version}) RETURNING id, workspace_id, vehicle_version, "
                                "schema_version, config, config_hash, source, confirmed_by")
    return rows[0]


def refused(exc_info) -> tuple[str, str | None]:
    return exc_info.value.sqlstate, exc_info.value.diag.constraint_name


def garage_catalog(url: str) -> dict:
    snapshot = identity_catalog(url)
    snapshot["triggers"] = _sql(url, "SELECT c.relname, g.tgname, g.tgtype, g.tgenabled FROM pg_trigger g "
                                     "JOIN pg_class c ON c.oid = g.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                                     "WHERE n.nspname = 'carvis' AND NOT g.tgisinternal ORDER BY 1, 2", fetch=True)
    snapshot["constraints"] = _sql(url, "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
                                        "FROM pg_constraint WHERE connamespace = 'carvis'::regnamespace ORDER BY 1, 2",
                                   fetch=True)
    return snapshot


# --- migration ------------------------------------------------------------------------------------

def test_round_trip_as_non_superuser_createrole_login(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", PREVIOUS))
    before = garage_catalog(scratch.db_admin)
    ok(run_alembic(migrator, "upgrade", HEAD))
    assert violations(scratch.db_admin) == []
    first = garage_catalog(scratch.db_admin)
    assert {r[0] for r in first["policies"]} >= {"vehicles", "vehicle_snapshots"}
    ok(run_alembic(migrator, "downgrade", PREVIOUS))
    assert garage_catalog(scratch.db_admin) == before  # uuid_v7 ACL restored, nothing left behind
    assert violations(scratch.db_admin) == []
    ok(run_alembic(migrator, "upgrade", HEAD))
    assert garage_catalog(scratch.db_admin) == first


def test_round_trip_as_superuser(scratch):
    ok(run_alembic(scratch.db_admin, "upgrade", HEAD))
    assert violations(scratch.db_admin, migration_login=None) == []
    ok(run_alembic(scratch.db_admin, "downgrade", PREVIOUS))
    assert violations(scratch.db_admin, migration_login=None) == []


@pytest.mark.parametrize("step", ["tables", "triggers", "policies"])
def test_forced_failure_rolls_back_without_drift(scratch, migrator, step):
    ok(run_alembic(migrator, "upgrade", PREVIOUS))
    before = garage_catalog(scratch.db_admin)
    result = run_alembic(migrator, "upgrade", HEAD, CARVIS_ENV="local", CARVIS_TEST_FAIL_AT=step)
    assert result.returncode != 0 and f"forced failure at {step}" in result.stderr
    assert garage_catalog(scratch.db_admin) == before


def test_forced_failure_in_downgrade_rolls_back(scratch, head):
    before = garage_catalog(scratch.db_admin)
    result = run_alembic(head, "downgrade", PREVIOUS, CARVIS_ENV="local", CARVIS_TEST_FAIL_AT="downgrade_drop")
    assert result.returncode != 0 and "forced failure at downgrade_drop" in result.stderr
    assert garage_catalog(scratch.db_admin) == before


def test_fail_hook_is_ignored_outside_local(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", PREVIOUS))
    ok(run_alembic(migrator, "upgrade", HEAD, CARVIS_ENV="production", CARVIS_TEST_FAIL_AT="tables"))


def test_downgrade_refuses_while_garage_rows_exist(scratch, head, people):
    confirm(scratch, people, "a", add_vehicle(scratch, people, "a"))
    before = garage_catalog(scratch.db_admin)
    result = run_alembic(head, "downgrade", PREVIOUS)
    assert result.returncode != 0 and "Garage tables contain rows" in result.stderr
    assert garage_catalog(scratch.db_admin) == before
    assert _sql(scratch.db_admin, "SELECT (SELECT count(*) FROM carvis.vehicles), "
                                  "(SELECT count(*) FROM carvis.vehicle_snapshots)", fetch=True) == [(1, 1)]


@pytest.mark.parametrize("ddl,message", [
    ("CREATE TABLE carvis.vehicles (x int)", "carvis.vehicles already exists; refusing"),
    ("CREATE TYPE carvis.vehicle_snapshots AS ENUM ('x')", "carvis.vehicle_snapshots already exists"),
    ("CREATE DOMAIN carvis.vehicles AS int", "A type named carvis.vehicles already exists"),
    ("CREATE FUNCTION carvis.vehicles_guard() RETURNS int LANGUAGE sql AS 'SELECT 1'",
     "carvis.vehicles_guard() already exists"),
])
def test_preflight_refuses_without_modification(scratch, migrator, ddl, message):
    ok(run_alembic(migrator, "upgrade", PREVIOUS))
    _sql(scratch.db_admin, "SET ROLE carvis_owner", ddl, "RESET ROLE")
    before = garage_catalog(scratch.db_admin)
    result = run_alembic(migrator, "upgrade", HEAD)
    assert result.returncode != 0 and message in result.stderr, result.stderr[-1500:]
    assert garage_catalog(scratch.db_admin) == before


def test_preflight_refuses_a_preexisting_relation_without_a_row_type(scratch, migrator):
    """An index has no row type, so only the relation check sees it."""
    ok(run_alembic(migrator, "upgrade", PREVIOUS))
    _sql(scratch.db_admin, "SET ROLE carvis_owner", "CREATE TABLE carvis.b3a_x (a int)",
         "CREATE INDEX vehicle_snapshots ON carvis.b3a_x (a)", "RESET ROLE")
    result = run_alembic(migrator, "upgrade", HEAD)
    assert result.returncode != 0 and "carvis.vehicle_snapshots already exists; refusing" in result.stderr
    assert "A type named" not in result.stderr


def test_explicit_revokes_hold_even_if_default_privileges_drifted(scratch, migrator):
    """The default-privilege revoke from 0003 is one layer; 0005's explicit revokes are another."""
    ok(run_alembic(migrator, "upgrade", PREVIOUS))
    _sql(scratch.db_admin, "ALTER DEFAULT PRIVILEGES FOR ROLE carvis_owner GRANT EXECUTE ON FUNCTIONS TO PUBLIC")
    try:
        ok(run_alembic(migrator, "upgrade", HEAD))
        for routine in ("vehicles_guard()", "vehicle_snapshots_confirm()", "vehicle_snapshots_immutable()"):
            assert _sql(scratch.db_admin, f"SELECT has_function_privilege('public', 'carvis.{routine}', 'EXECUTE')",
                        fetch=True) == [(False,)], routine
    finally:
        ok(run_alembic(migrator, "downgrade", PREVIOUS))
        _sql(scratch.db_admin, "ALTER DEFAULT PRIVILEGES FOR ROLE carvis_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")


# --- catalog --------------------------------------------------------------------------------------

@pytest.mark.parametrize("setup,code", [
    (["ALTER TABLE carvis.vehicles NO FORCE ROW LEVEL SECURITY"], "rls_not_forced:vehicles"),
    (["ALTER TABLE carvis.vehicle_snapshots NO FORCE ROW LEVEL SECURITY"], "rls_not_forced:vehicle_snapshots"),
    (["GRANT DELETE ON carvis.vehicles TO carvis_app"], "table_privileges:carvis_app:vehicles"),
    (["GRANT UPDATE (config) ON carvis.vehicle_snapshots TO carvis_app"],
     "table_privileges:carvis_app:vehicle_snapshots"),
    (["GRANT INSERT (config) ON carvis.vehicle_snapshots TO carvis_app"],
     "table_privileges:carvis_app:vehicle_snapshots"),
    (["GRANT INSERT ON carvis.vehicles TO carvis_worker"], "table_privileges:carvis_worker:vehicles"),
    (["GRANT SELECT ON carvis.vehicles TO carvis_bootstrap"], "table_privileges:carvis_bootstrap:vehicles"),
    (["REVOKE UPDATE (archived_at) ON carvis.vehicles FROM carvis_app"], "table_privileges:carvis_app:vehicles"),
    (["REVOKE EXECUTE ON FUNCTION carvis.uuid_v7() FROM carvis_app"], "routine_acl:carvis.uuid_v7()"),
    (["GRANT EXECUTE ON FUNCTION carvis.uuid_v7() TO carvis_worker"], "routine_acl:carvis.uuid_v7()"),
    (["ALTER TABLE carvis.vehicle_snapshots DISABLE TRIGGER vehicle_snapshots_confirm"],
     "required_trigger:vehicle_snapshots:insert"),
    (["ALTER TABLE carvis.vehicle_snapshots ENABLE REPLICA TRIGGER vehicle_snapshots_confirm"],
     "required_trigger:vehicle_snapshots:insert"),
    (["DROP TRIGGER vehicle_snapshots_immutable ON carvis.vehicle_snapshots"],
     "required_trigger:vehicle_snapshots:update"),
    (["DROP TRIGGER vehicle_snapshots_immutable ON carvis.vehicle_snapshots",
      "CREATE TRIGGER vehicle_snapshots_immutable BEFORE UPDATE ON carvis.vehicle_snapshots FOR EACH ROW "
      "EXECUTE FUNCTION carvis.vehicle_snapshots_immutable()"], "required_trigger:vehicle_snapshots:delete"),
    (["DROP TRIGGER vehicle_snapshots_immutable ON carvis.vehicle_snapshots",
      "CREATE TRIGGER vehicle_snapshots_immutable AFTER UPDATE OR DELETE ON carvis.vehicle_snapshots FOR EACH ROW "
      "EXECUTE FUNCTION carvis.vehicle_snapshots_immutable()"], "required_trigger:vehicle_snapshots:update"),
    (["ALTER TABLE carvis.vehicle_snapshots DISABLE TRIGGER vehicle_snapshots_no_truncate"],
     "required_trigger:vehicle_snapshots:truncate"),
])
def test_catalog_check_detects_garage_violations(scratch, head, setup, code):
    assert violations(scratch.db_admin) == []
    _sql(scratch.db_admin, "SET ROLE carvis_owner", *setup, "RESET ROLE")
    assert code in violations(scratch.db_admin)


def test_composite_snapshot_foreign_key_columns_are_not_null(scratch, head):
    rows = _sql(scratch.db_admin, "SELECT a.attname, a.attnotnull FROM pg_constraint c "
                                  "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
                                  "WHERE c.conname = 'vehicle_snapshots_vehicle_fk' ORDER BY 1", fetch=True)
    assert rows == [("vehicle_id", True), ("workspace_id", True)]


# --- isolation (I1) -------------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["carvis_app", "carvis_worker"])
def test_no_context_means_no_rows_and_inserts_fail(scratch, people, role):
    vehicle = add_vehicle(scratch, people, "a")
    confirm(scratch, people, "a", vehicle)
    for table in ("vehicles", "vehicle_snapshots"):
        assert as_role(scratch.db_admin, role, [f"SELECT * FROM carvis.{table}"], fetch=True) == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
        as_role(scratch.db_admin, "carvis_app", [f"INSERT INTO carvis.vehicles (workspace_id, year, make, model) "
                                                 f"VALUES ('{people['wa']}', 2019, 'Ford', 'F-150')"])


@pytest.mark.parametrize("role", ["carvis_app", "carvis_worker"])
def test_unfiltered_queries_return_only_the_callers_rows(scratch, people, role):
    va = add_vehicle(scratch, people, "a")
    vb = add_vehicle(scratch, people, "b")
    vs = add_vehicle(scratch, people, "c", workspace=people["ws"])
    for v, who in ((va, "a"), (vb, "b"), (vs, "c")):
        confirm(scratch, people, who, v)
    seen = {who: {str(r[0]) for r in app(scratch, people, who, "SELECT id FROM carvis.vehicles", role=role)}
            for who in "abc"}
    assert seen == {"a": {va, vs}, "b": {vb}, "c": {vs}}
    snapshots = {who: {str(r[0]) for r in app(scratch, people, who, "SELECT vehicle_id FROM carvis.vehicle_snapshots",
                                              role=role)} for who in "abc"}
    assert snapshots == {"a": {va, vs}, "b": {vb}, "c": {vs}}


def test_app_cannot_write_another_workspace(scratch, people):
    vb = add_vehicle(scratch, people, "b")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
        add_vehicle(scratch, people, "a", workspace=people["wb"])
    assert app(scratch, people, "a", f"UPDATE carvis.vehicles SET make = 'X' WHERE id = '{vb}' RETURNING id") == []
    assert _sql(scratch.db_admin, f"SELECT make, version FROM carvis.vehicles WHERE id = '{vb}'",
                fetch=True) == [("Ford", 1)]


def test_unfiltered_update_changes_only_the_callers_vehicles(scratch, people):
    """An UPDATE without WHERE reads no column, so only the UPDATE policy's USING bounds its targets."""
    va = add_vehicle(scratch, people, "a")
    vb = add_vehicle(scratch, people, "b")
    app(scratch, people, "a", "UPDATE carvis.vehicles SET make = 'Changed'", fetch=False)
    assert _sql(scratch.db_admin, f"SELECT id::text, make FROM carvis.vehicles WHERE id IN ('{va}', '{vb}') ORDER BY make",
                fetch=True) == sorted([(va, "Changed"), (vb, "Ford")], key=lambda r: r[1])


def test_app_cannot_move_a_vehicle_between_workspaces(scratch, people):
    va = add_vehicle(scratch, people, "a")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app(scratch, people, "a", f"UPDATE carvis.vehicles SET workspace_id = '{people['ws']}' WHERE id = '{va}'")


def test_worker_cannot_write(scratch, people):
    va = add_vehicle(scratch, people, "a")
    for statement in (f"INSERT INTO carvis.vehicles (workspace_id, year, make, model) VALUES "
                      f"('{people['wa']}', 2019, 'Ford', 'F-150')",
                      f"UPDATE carvis.vehicles SET make = 'X' WHERE id = '{va}'",
                      f"INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version) VALUES ('{va}', 1)"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app(scratch, people, "a", statement, fetch=False, role="carvis_worker")


@pytest.mark.parametrize("role", ["carvis_bootstrap", "carvis_provisioner"])
def test_bootstrap_and_provisioner_are_denied_the_garage(scratch, people, role):
    for table in ("vehicles", "vehicle_snapshots"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            as_role(scratch.db_admin, role, [f"SELECT 1 FROM carvis.{table}"])


def test_raw_login_is_denied_the_garage(scratch, people, login):
    for statement in ("SELECT 1 FROM carvis.vehicles", "SELECT 1 FROM carvis.vehicle_snapshots",
                      "SELECT carvis.uuid_v7()"):
        with psycopg.connect(login) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_issuer_roles_get_nothing_on_garage_objects(scratch, migrator):
    _sql(scratch.admin, "CREATE ROLE anon NOLOGIN", "CREATE ROLE authenticated NOLOGIN",
         "CREATE ROLE service_role NOLOGIN")
    try:
        ok(run_alembic(migrator, "upgrade", HEAD))
        assert violations(scratch.db_admin) == []
        for role in ("anon", "authenticated", "service_role"):
            for table in ("vehicles", "vehicle_snapshots"):
                assert _sql(scratch.db_admin, f"SELECT has_table_privilege('{role}', 'carvis.{table}', 'SELECT'), "
                                              f"has_table_privilege('{role}', 'carvis.{table}', 'INSERT')",
                            fetch=True) == [(False, False)]
            for routine in ("vehicles_guard()", "vehicle_snapshots_confirm()", "vehicle_snapshots_immutable()"):
                assert _sql(scratch.db_admin, f"SELECT has_function_privilege('{role}', 'carvis.{routine}', "
                                              "'EXECUTE')", fetch=True) == [(False,)]
    finally:
        ok(run_alembic(migrator, "downgrade", "0003_runtime_roles"))
        for role in ("anon", "authenticated", "service_role"):
            _sql(scratch.admin, f"DROP ROLE IF EXISTS {role}")


# --- confirm (I2, I3, I7, I8) ---------------------------------------------------------------------

def test_confirm_derives_every_column(scratch, people):
    va = add_vehicle(scratch, people, "a", vin=VIN, trim="XLT", not_applicable=["transmission"],
                     production_date="2019-03", source="vin_decode")
    sid, workspace, version, schema_version, config, digest, source, confirmed_by = confirm(scratch, people, "a", va)
    assert (str(workspace), version, schema_version, source, str(confirmed_by)) == (
        people["wa"], 1, 1, "vin_decode", people["a"])
    assert config["vin"] == VIN and config["year"] == 2019 and config["make"] == "Ford" and config["schema_version"] == 1
    states = {name: config["attributes"][name] for name in ATTRIBUTES}
    assert states["trim"] == {"state": "known", "value": "XLT"}
    assert states["production_date"] == {"state": "known", "value": "2019-03"}
    assert states["transmission"] == {"state": "not_applicable"}
    assert all(states[n] == {"state": "unknown"} for n in ATTRIBUTES if n not in ("trim", "transmission",
                                                                                  "production_date"))
    recomputed = _sql(scratch.db_admin, f"SELECT encode(sha256(convert_to(config::text, 'UTF8')), 'hex') "
                                        f"FROM carvis.vehicle_snapshots WHERE id = '{sid}'", fetch=True)[0][0]
    assert digest == recomputed and len(digest) == 64
    version7 = uuid.UUID(str(sid)).version
    assert version7 == 7


def test_every_attribute_has_three_states(scratch, people):
    for name in ATTRIBUTES:
        value = "2020-01" if name == "production_date" else "v"
        known = add_vehicle(scratch, people, "a", **{name: value})
        na = add_vehicle(scratch, people, "a", not_applicable=[name])
        unknown = add_vehicle(scratch, people, "a")
        for vehicle, expected in ((known, {"state": "known", "value": value}), (na, {"state": "not_applicable"}),
                                  (unknown, {"state": "unknown"})):
            assert confirm(scratch, people, "a", vehicle)[4]["attributes"][name] == expected


def test_equal_configurations_hash_equally(scratch, people):
    one = confirm(scratch, people, "a", add_vehicle(scratch, people, "a", trim="XLT"))
    two = confirm(scratch, people, "a", add_vehicle(scratch, people, "a", trim="XLT"))
    three = confirm(scratch, people, "a", add_vehicle(scratch, people, "a", trim="Lariat"))
    assert one[5] == two[5] != three[5]
    canonical = json.dumps(one[4], sort_keys=True)
    assert canonical == json.dumps(two[4], sort_keys=True)


@pytest.mark.parametrize("column,value", [("config", "'{{}}'::jsonb"), ("workspace_id", "'{wa}'"),
                                          ("confirmed_by", "'{a}'"), ("id", "gen_random_uuid()"),
                                          ("source", "'manual'"), ("config_hash", "repeat('0', 64)"),
                                          ("confirmed_at", "now()"), ("schema_version", "1")])
def test_app_cannot_supply_derived_columns(scratch, people, column, value):
    va = add_vehicle(scratch, people, "a")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
        app(scratch, people, "a", f"INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version, {column}) "
                                  f"VALUES ('{va}', 1, {value.format(**people)})", fetch=False)


def test_other_workspace_vehicle_is_refused_like_a_missing_one(scratch, people):
    vb = add_vehicle(scratch, people, "b")
    with pytest.raises(psycopg.Error) as other:
        confirm(scratch, people, "a", vb)
    with pytest.raises(psycopg.Error) as missing:
        confirm(scratch, people, "a", str(uuid.uuid4()))
    assert refused(other) == refused(missing) == ("23503", "vehicle_snapshots_vehicle_visible")
    assert str(other.value).splitlines()[0] == str(missing.value).splitlines()[0]


def test_shop_vehicle_is_confirmable_by_each_member(scratch, people):
    """Codex F1: each confirmation is its own snapshot with its own confirmer."""
    vs = add_vehicle(scratch, people, "a", workspace=people["ws"])
    by_a = confirm(scratch, people, "a", vs)
    by_c = confirm(scratch, people, "c", vs)
    again = confirm(scratch, people, "a", vs)
    assert len({by_a[0], by_c[0], again[0]}) == 3
    assert (str(by_a[7]), str(by_c[7]), str(again[7])) == (people["a"], people["c"], people["a"])
    assert by_a[5] == by_c[5] == again[5]  # same configuration, same hash
    with pytest.raises(psycopg.Error) as outsider:
        confirm(scratch, people, "b", vs)
    assert refused(outsider) == ("23503", "vehicle_snapshots_vehicle_visible")


def test_archived_vehicle_is_refused(scratch, people):
    va = add_vehicle(scratch, people, "a")
    app(scratch, people, "a", f"UPDATE carvis.vehicles SET archived_at = now() WHERE id = '{va}'", fetch=False)
    for version in (1, 2):
        with pytest.raises(psycopg.Error) as exc:
            confirm(scratch, people, "a", va, version)
        assert refused(exc) == ("55000", "vehicle_snapshots_vehicle_not_archived")


def test_stale_version_is_refused(scratch, people):
    va = add_vehicle(scratch, people, "a")
    confirm(scratch, people, "a", va, 1)
    app(scratch, people, "a", f"UPDATE carvis.vehicles SET trim = 'XLT' WHERE id = '{va}'", fetch=False)
    for version in (1, 3):
        with pytest.raises(psycopg.Error) as exc:
            confirm(scratch, people, "a", va, version)
        assert refused(exc) == ("55000", "vehicle_snapshots_current_version")
    assert confirm(scratch, people, "a", va, 2)[4]["attributes"]["trim"] == {"state": "known", "value": "XLT"}


def test_null_version_is_refused(scratch, people):
    va = add_vehicle(scratch, people, "a")
    with pytest.raises(psycopg.Error) as exc:
        app(scratch, people, "a", f"INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version) "
                                  f"VALUES ('{va}', NULL)", fetch=False)
    assert refused(exc) == ("55000", "vehicle_snapshots_current_version")


def test_missing_principal_is_refused(scratch, people):
    va = add_vehicle(scratch, people, "a")
    settings = {"app.workspace_ids": "{" + people["wa"] + "}"}
    with pytest.raises(psycopg.Error) as exc:
        as_role(scratch.db_admin, "carvis_app", [f"INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version) "
                                                 f"VALUES ('{va}', 1)"], settings)
    assert refused(exc) == ("42501", "vehicle_snapshots_confirmed_by_context")


def test_merge_goes_through_the_confirm_trigger_and_copy_is_refused(scratch, people):
    va = add_vehicle(scratch, people, "a", trim="XLT")
    merge = (f"MERGE INTO carvis.vehicle_snapshots AS s USING (SELECT '{va}'::uuid AS v) AS src ON false "
             "WHEN NOT MATCHED THEN INSERT (vehicle_id, vehicle_version) VALUES (src.v, {version})")
    app(scratch, people, "a", [merge.format(version=1)], fetch=False)
    rows = _sql(scratch.db_admin, f"SELECT confirmed_by, config -> 'attributes' -> 'trim' FROM carvis.vehicle_snapshots "
                                  f"WHERE vehicle_id = '{va}'", fetch=True)
    assert [(str(r[0]), r[1]) for r in rows] == [(people["a"], {"state": "known", "value": "XLT"})]
    with pytest.raises(psycopg.Error) as exc:
        app(scratch, people, "a", [merge.format(version=7)], fetch=False)
    assert refused(exc) == ("55000", "vehicle_snapshots_current_version")
    # COPY FROM is refused outright on a table with row-level security for a role subject to it (PG16 sql-copy).
    with psycopg.connect(scratch.db_admin) as conn:
        conn.execute("SET LOCAL ROLE carvis_app")
        for name, value in ctx(people, "a").items():
            conn.execute("SELECT set_config(%s, %s, true)", (name, value))
        with pytest.raises(psycopg.errors.FeatureNotSupported, match="row-level security"):
            with conn.cursor().copy("COPY carvis.vehicle_snapshots (vehicle_id, vehicle_version) FROM STDIN") as copy:
                copy.write_row((va, 1))


def test_owner_inserts_are_still_derived_and_refused(scratch, people):
    """With forced RLS lifted in one transaction, the owner's supplied values are overwritten (DML boundary)."""
    va = add_vehicle(scratch, people, "a", trim="XLT")
    with psycopg.connect(scratch.db_admin) as conn:
        conn.execute("SET LOCAL ROLE carvis_owner")
        conn.execute("ALTER TABLE carvis.vehicles NO FORCE ROW LEVEL SECURITY")
        conn.execute("ALTER TABLE carvis.vehicle_snapshots NO FORCE ROW LEVEL SECURITY")
        conn.execute("SELECT set_config('app.user_id', %s, true)", (people["a"],))
        row = conn.execute("INSERT INTO carvis.vehicle_snapshots (id, workspace_id, vehicle_id, vehicle_version, "
                           "schema_version, config, config_hash, source, confirmed_by, confirmed_at) VALUES "
                           "(gen_random_uuid(), %s, %s, 1, 1, '{\"schema_version\": 1, \"forged\": true}', "
                           "repeat('0', 64), 'manual', %s, '2000-01-01') "
                           "RETURNING workspace_id, config, config_hash, confirmed_at",
                           (people["wb"], va, people["b"])).fetchone()
        assert str(row[0]) == people["wa"] and "forged" not in row[1] and row[2] != "0" * 64
        assert row[3].year >= 2026
        conn.execute(f"UPDATE carvis.vehicles SET archived_at = now() WHERE id = '{va}'")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            conn.execute("INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version) VALUES (%s, 2)", (va,))
        conn.rollback()


def test_composite_foreign_key_rejects_a_mismatched_workspace(scratch, people):
    """I6: with the confirm trigger disabled (superuser DDL), the NOT NULL composite FK still binds a snapshot to its
    vehicle's workspace."""
    va = add_vehicle(scratch, people, "a")
    with psycopg.connect(scratch.db_admin) as conn:
        conn.execute("ALTER TABLE carvis.vehicle_snapshots DISABLE TRIGGER vehicle_snapshots_confirm")
        for workspace in (people["wb"], None):
            with pytest.raises((psycopg.errors.ForeignKeyViolation, psycopg.errors.NotNullViolation)):
                with conn.transaction():
                    conn.execute("INSERT INTO carvis.vehicle_snapshots (workspace_id, vehicle_id, vehicle_version, "
                                 "schema_version, config, config_hash, source, confirmed_by, confirmed_at) VALUES "
                                 "(%s, %s, 1, 1, '{\"schema_version\": 1}', repeat('0', 64), 'manual', %s, now())",
                                 (workspace, va, people["a"]))
        conn.rollback()


# --- concurrency (I2) -----------------------------------------------------------------------------

def _tenant_connection(scratch, people, who):
    conn = psycopg.connect(scratch.db_admin)
    conn.execute("SET LOCAL ROLE carvis_app")
    for name, value in ctx(people, who).items():
        conn.execute("SELECT set_config(%s, %s, true)", (name, value))
    return conn


def _wait_until_blocked(scratch, pid: int) -> None:
    for _ in range(200):
        if _sql(scratch.db_admin, f"SELECT wait_event_type FROM pg_stat_activity WHERE pid = {pid}",
                fetch=True)[0][0] == "Lock":
            return
        time.sleep(0.02)
    raise AssertionError("the second transaction never blocked")


def _in_thread(fn):
    result: dict = {}

    def run():
        try:
            result["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the test
            result["error"] = exc
    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def test_edit_waits_for_an_open_confirmation(scratch, people):
    va = add_vehicle(scratch, people, "a")
    confirmer = _tenant_connection(scratch, people, "a")
    editor = _tenant_connection(scratch, people, "a")
    try:
        confirmer.execute("INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version) VALUES (%s, 1)", (va,))
        editor_pid = editor.info.backend_pid
        thread, result = _in_thread(lambda: editor.execute(
            "UPDATE carvis.vehicles SET trim = 'XLT' WHERE id = %s RETURNING version", (va,)).fetchone())
        _wait_until_blocked(scratch, editor_pid)
        confirmer.commit()
        thread.join(10)
        editor.commit()
        assert result.get("value") == (2,)
    finally:
        confirmer.close()
        editor.close()
    assert _sql(scratch.db_admin, f"SELECT vehicle_version FROM carvis.vehicle_snapshots WHERE vehicle_id = '{va}'",
                fetch=True) == [(1,)]


@pytest.mark.parametrize("change,constraint", [("trim = 'XLT'", "vehicle_snapshots_current_version"),
                                               ("archived_at = now()", "vehicle_snapshots_vehicle_not_archived")])
def test_confirmation_waiting_on_an_edit_sees_the_committed_edit(scratch, people, change, constraint):
    va = add_vehicle(scratch, people, "a")
    editor = _tenant_connection(scratch, people, "a")
    confirmer = _tenant_connection(scratch, people, "a")
    try:
        editor.execute(f"UPDATE carvis.vehicles SET {change} WHERE id = %s", (va,))
        pid = confirmer.info.backend_pid
        thread, result = _in_thread(lambda: confirmer.execute(
            "INSERT INTO carvis.vehicle_snapshots (vehicle_id, vehicle_version) VALUES (%s, 1)", (va,)))
        _wait_until_blocked(scratch, pid)
        editor.commit()
        thread.join(10)
        error = result.get("error")
        assert isinstance(error, psycopg.Error)
        assert (error.sqlstate, error.diag.constraint_name) == ("55000", constraint)
    finally:
        editor.close()
        confirmer.close()


# --- immutability (I4) and the vehicle guard (I5) --------------------------------------------------

def test_app_cannot_update_delete_or_truncate_snapshots(scratch, people):
    va = add_vehicle(scratch, people, "a")
    confirm(scratch, people, "a", va)
    for statement in ("UPDATE carvis.vehicle_snapshots SET vehicle_version = 1",
                      "DELETE FROM carvis.vehicle_snapshots", "TRUNCATE carvis.vehicle_snapshots",
                      "DELETE FROM carvis.vehicles", "TRUNCATE carvis.vehicles"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app(scratch, people, "a", statement, fetch=False)


@pytest.mark.parametrize("statement", ["UPDATE carvis.vehicle_snapshots SET source = 'manual'",
                                       "DELETE FROM carvis.vehicle_snapshots",
                                       "TRUNCATE carvis.vehicle_snapshots"])
def test_owner_cannot_change_snapshots(scratch, people, statement):
    confirm(scratch, people, "a", add_vehicle(scratch, people, "a"))
    with psycopg.connect(scratch.db_admin) as conn:
        conn.execute("SET LOCAL ROLE carvis_owner")
        conn.execute("ALTER TABLE carvis.vehicle_snapshots NO FORCE ROW LEVEL SECURITY")
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(statement)
        assert refused(exc) == ("55000", "vehicle_snapshots_immutable")
        conn.rollback()
    assert _sql(scratch.db_admin, "SELECT count(*) FROM carvis.vehicle_snapshots", fetch=True) == [(1,)]


def test_every_update_is_one_version(scratch, people):
    va = add_vehicle(scratch, people, "a")
    assert app(scratch, people, "a", f"UPDATE carvis.vehicles SET trim = 'XLT' WHERE id = '{va}' RETURNING version") \
        == [(2,)]
    assert app(scratch, people, "a", f"UPDATE carvis.vehicles SET trim = 'XLT' WHERE id = '{va}' RETURNING version") \
        == [(3,)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app(scratch, people, "a", f"UPDATE carvis.vehicles SET version = 1 WHERE id = '{va}'", fetch=False)


def test_archiving_is_terminal_and_timestamped_by_the_server(scratch, people):
    va = add_vehicle(scratch, people, "a")
    row = app(scratch, people, "a", f"UPDATE carvis.vehicles SET archived_at = '2000-01-01' WHERE id = '{va}' "
                                    "RETURNING version, archived_at")[0]
    assert row[0] == 2 and row[1].year >= 2026
    for change in ("archived_at = NULL", "trim = 'XLT'"):
        with pytest.raises(psycopg.Error) as exc:
            app(scratch, people, "a", f"UPDATE carvis.vehicles SET {change} WHERE id = '{va}'", fetch=False)
        assert refused(exc) == ("55000", "vehicles_archived_is_terminal")


@pytest.mark.parametrize("change", ["workspace_id = gen_random_uuid()", "source = 'vin_decode'", "id = gen_random_uuid()",
                                    "created_at = now() - interval '1 day'"])
def test_identity_columns_are_immutable_for_the_owner(scratch, people, change):
    va = add_vehicle(scratch, people, "a")
    with psycopg.connect(scratch.db_admin) as conn:
        conn.execute("SET LOCAL ROLE carvis_owner")
        conn.execute("ALTER TABLE carvis.vehicles NO FORCE ROW LEVEL SECURITY")
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(f"UPDATE carvis.vehicles SET {change} WHERE id = '{va}'")
        assert refused(exc) == ("23514", "vehicles_identity_immutable")
        conn.rollback()


@pytest.mark.parametrize("columns,constraint", [
    ({"vin": "1m8gdm9axkp042788"}, "vehicles_vin_format"),
    ({"vin": "1M8GDM9AXKP04278I"}, "vehicles_vin_format"),
    ({"vin": "1M8GDM9AXKP04278O"}, "vehicles_vin_format"),
    ({"vin": "1M8GDM9AXKP04278Q"}, "vehicles_vin_format"),
    ({"vin": "1M8GDM9AXKP04278"}, "vehicles_vin_format"),
    ({"vin": "1M8GDM9AXKP0427888"}, "vehicles_vin_format"),
    ({"year": 1899}, "vehicles_year_range"),
    ({"trim": "XLT", "not_applicable": ["trim"]}, "vehicles_value_or_not_applicable"),
    ({"production_plant": "Dearborn", "not_applicable": ["production_plant"]}, "vehicles_value_or_not_applicable"),
    ({"not_applicable": ["colour"]}, "vehicles_not_applicable_known"),
    ({"production_date": "2019-13"}, "vehicles_production_date_value"),
    ({"production_date": "2019-3"}, "vehicles_production_date_value"),
    ({"trim": ""}, "vehicles_trim_value"),
    ({"source": "guess"}, "vehicles_source_value"),
])
def test_vehicle_checks(scratch, people, columns, constraint):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        add_vehicle(scratch, people, "a", **columns)
    assert exc.value.diag.constraint_name == constraint


def test_vin_is_unique_per_workspace_including_archived(scratch, people):
    va = add_vehicle(scratch, people, "a", vin=VIN)
    with pytest.raises(psycopg.errors.UniqueViolation) as exc:
        add_vehicle(scratch, people, "a", vin=VIN)
    assert exc.value.diag.constraint_name == "vehicles_workspace_vin_key"
    app(scratch, people, "a", f"UPDATE carvis.vehicles SET archived_at = now() WHERE id = '{va}'", fetch=False)
    with pytest.raises(psycopg.errors.UniqueViolation) as archived:
        add_vehicle(scratch, people, "a", vin=VIN)
    assert archived.value.diag.constraint_name == "vehicles_workspace_vin_key"
    add_vehicle(scratch, people, "b", vin=VIN)  # another workspace is unaffected
    add_vehicle(scratch, people, "a")  # VIN-less vehicles are unaffected
    add_vehicle(scratch, people, "a")


def test_duplicate_vin_in_another_workspace_is_refused_by_rls_not_the_unique_key(scratch, people):
    """No VIN oracle: WITH CHECK refuses a foreign workspace before the unique index is consulted."""
    add_vehicle(scratch, people, "b", vin=VIN)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
        add_vehicle(scratch, people, "a", workspace=people["wb"], vin=VIN)


def test_vehicle_list_by_workspace_uses_an_index(scratch, people):
    for _ in range(3):
        add_vehicle(scratch, people, "a")
    with psycopg.connect(scratch.db_admin) as conn:
        conn.execute("SET LOCAL enable_seqscan = off")
        plan = conn.execute(f"EXPLAIN SELECT id FROM carvis.vehicles WHERE workspace_id = '{people['wa']}' "
                            "AND archived_at IS NULL").fetchall()
    assert "vehicles_workspace" in " ".join(r[0] for r in plan)


def test_snapshot_hash_matches_python_sha256_of_postgres_text(scratch, people):
    sid = confirm(scratch, people, "a", add_vehicle(scratch, people, "a", vin=VIN))[0]
    text, digest = _sql(scratch.db_admin, f"SELECT config::text, config_hash FROM carvis.vehicle_snapshots "
                                          f"WHERE id = '{sid}'", fetch=True)[0]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == digest
