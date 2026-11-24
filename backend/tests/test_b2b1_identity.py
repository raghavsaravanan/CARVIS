"""M2 B2b-1: identity tables, forced RLS, ensure_principal and the catalog check, on real PostgreSQL 16.

Doc 04 "Validation" items covered here at database level: 1, 2, 6, 7 (worker part), 8, 10, 12 (with
the identity tables present), 13, 14 and 15. Items 3, 4, 5 and 16 (session context and pooling) belong
to B2b-2. Same server requirements as ``test_b1_migrations.py``; migrations run as a non-superuser
``CREATEROLE`` database owner unless a test says otherwise.
"""
from __future__ import annotations

import threading
import time
import uuid

import psycopg
import pytest

from tests.test_b1_migrations import PASSWORD, _sql, _url, admin_url, scratch  # noqa: F401
from tests.test_b2a_migrations import MIGRATOR, full_catalog, members_of, migrator, ok, run_alembic  # noqa: F401
from tests.test_b2a_runtime_login import RUNTIME, runtime_login

HEAD = "0004_identity"
B2A_HEAD = "0003_runtime_roles"
ISSUER = "https://issuer.example.test/auth/v1"


# --- helpers ------------------------------------------------------------------------------------

def violations(url: str, search_path: str | None = None) -> list[str]:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from db.catalog import violations as check

    engine = create_engine(_url(url).replace("postgresql://", "postgresql+psycopg://", 1), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            if search_path:
                connection.exec_driver_sql(f"SET search_path = {search_path}")
            return check(connection)
    finally:
        engine.dispose()


def identity_catalog(url: str) -> dict:
    snapshot = full_catalog(url)
    snapshot["policies"] = _sql(url, "SELECT tablename, policyname, roles::text, cmd, qual, with_check "
                                     "FROM pg_policies WHERE schemaname = 'carvis' ORDER BY 1, 2", fetch=True)
    snapshot["routines"] = _sql(url, "SELECT p.oid::regprocedure::text, pg_get_userbyid(p.proowner), p.prosecdef, "
                                     "p.proconfig::text, p.proacl::text FROM pg_proc p JOIN pg_namespace n "
                                     "ON n.oid = p.pronamespace WHERE n.nspname = 'carvis' ORDER BY 1", fetch=True)
    snapshot["types"] = _sql(url, "SELECT t.typname, t.typacl::text FROM pg_type t JOIN pg_namespace n "
                                  "ON n.oid = t.typnamespace WHERE n.nspname = 'carvis' ORDER BY 1", fetch=True)
    snapshot["columns"] = _sql(url, "SELECT c.relname, a.attname, a.attacl::text FROM pg_attribute a JOIN pg_class c "
                                    "ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                                    "WHERE n.nspname = 'carvis' AND a.attacl IS NOT NULL ORDER BY 1, 2", fetch=True)
    return snapshot


@pytest.fixture
def head(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD))
    return migrator


@pytest.fixture
def login(scratch, head):
    """A provisioned runtime login (INHERIT FALSE members of carvis_app and carvis_bootstrap)."""
    url = scratch.login(RUNTIME)
    assert runtime_login(head, "grant", RUNTIME).returncode == 0
    return url


def ensure(login_url: str, subject: str, email: str | None = "tech@example.test", issuer: str = ISSUER,
           isolation: str | None = None):
    with psycopg.connect(login_url) as conn:
        if isolation:
            conn.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        conn.execute("SET LOCAL ROLE carvis_bootstrap")
        cursor = conn.execute("SELECT * FROM carvis.ensure_principal(%s, %s, %s)", (issuer, subject, email))
        columns = [d.name for d in cursor.description]
        row = cursor.fetchone()
        leftover = conn.execute("SELECT current_setting('app.bootstrap_issuer', true), "
                                "current_setting('app.bootstrap_subject', true), "
                                "current_setting('app.bootstrap_user_id', true)").fetchone()
    return columns, row, leftover


def counts(url: str) -> tuple[int, int, int]:
    """Row counts as superuser (bypasses RLS)."""
    return tuple(_sql(url, f"SELECT count(*) FROM carvis.{t}", fetch=True)[0][0]
                 for t in ("users", "workspaces", "memberships"))


def as_role(url: str, role: str, statements: list[str], settings: dict[str, str] | None = None, fetch=False):
    with psycopg.connect(url) as conn:
        conn.execute(f"SET LOCAL ROLE {role}")
        for name, value in (settings or {}).items():
            conn.execute("SELECT set_config(%s, %s, true)", (name, value))
        cursor = None
        for statement in statements:
            cursor = conn.execute(statement)
        return cursor.fetchall() if fetch and cursor is not None else None


# --- migration ----------------------------------------------------------------------------------

def test_round_trip_as_non_superuser_createrole_login(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD))
    assert violations(scratch.db_admin) == []
    first = identity_catalog(scratch.db_admin)
    assert {r[0] for r in first["policies"]} == {"users", "workspaces", "memberships"}
    assert members_of(scratch.db_admin, "carvis_provisioner") == [(MIGRATOR, "postgres", True, False, False)]
    ok(run_alembic(migrator, "downgrade", B2A_HEAD))
    down = identity_catalog(scratch.db_admin)
    assert down["policies"] == [] and down["routines"] == [] and down["version"] == [(B2A_HEAD,)]
    assert violations(scratch.db_admin) == []
    assert members_of(scratch.db_admin, "carvis_provisioner") == [(MIGRATOR, "postgres", True, False, False)]
    ok(run_alembic(migrator, "upgrade", HEAD))
    assert identity_catalog(scratch.db_admin) == first


def test_round_trip_as_superuser(scratch):
    ok(run_alembic(scratch.db_admin, "upgrade", HEAD))
    assert violations(scratch.db_admin) == []
    ok(run_alembic(scratch.db_admin, "downgrade", "base"))
    assert not [row for row in full_catalog(scratch.db_admin)["roles"]]


@pytest.mark.parametrize("step", ["tables", "policies", "temporary_grant", "definer"])
def test_forced_failure_rolls_back_without_drift(scratch, migrator, step):
    ok(run_alembic(migrator, "upgrade", B2A_HEAD))
    before = identity_catalog(scratch.db_admin)
    result = run_alembic(migrator, "upgrade", HEAD, CARVIS_ENV="local", CARVIS_TEST_FAIL_AT=step)
    assert result.returncode != 0 and f"forced failure at {step}" in result.stderr
    assert identity_catalog(scratch.db_admin) == before
    ok(run_alembic(migrator, "upgrade", HEAD))


def test_forced_failure_in_downgrade_rolls_back(scratch, head):
    before = identity_catalog(scratch.db_admin)
    result = run_alembic(head, "downgrade", B2A_HEAD, CARVIS_ENV="local", CARVIS_TEST_FAIL_AT="downgrade_drop")
    assert result.returncode != 0 and "forced failure at downgrade_drop" in result.stderr
    assert identity_catalog(scratch.db_admin) == before


def test_downgrade_refuses_while_identity_rows_exist(scratch, head, login):
    ensure(login, "user-a")
    before = identity_catalog(scratch.db_admin)
    result = run_alembic(head, "downgrade", B2A_HEAD)
    assert result.returncode != 0 and "Identity tables contain rows" in result.stderr
    assert identity_catalog(scratch.db_admin) == before and counts(scratch.db_admin) == (1, 1, 1)


@pytest.mark.parametrize("setup,message", [
    (["ALTER ROLE carvis_provisioner BYPASSRLS"], "carvis_provisioner is missing or has LOGIN"),
    (["ALTER ROLE carvis_provisioner LOGIN"], "carvis_provisioner is missing or has LOGIN"),
    (["ALTER ROLE carvis_bootstrap BYPASSRLS"], "carvis_bootstrap is missing or has LOGIN"),
    (["GRANT pg_read_all_data TO carvis_provisioner"], "carvis_provisioner is a member of another role"),
    (["CREATE ROLE b1_other NOLOGIN", "GRANT carvis_provisioner TO b1_other"], "member other than the migration"),
])
def test_preflight_refuses_without_modification(scratch, migrator, setup, message):
    ok(run_alembic(migrator, "upgrade", B2A_HEAD))
    _sql(scratch.admin, *setup)
    before = identity_catalog(scratch.db_admin)
    result = run_alembic(migrator, "upgrade", HEAD)
    assert result.returncode != 0 and message in result.stderr, result.stderr[-1500:]
    assert identity_catalog(scratch.db_admin) == before


def test_preflight_refuses_a_preexisting_table(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", B2A_HEAD))
    _sql(scratch.db_admin, "SET ROLE carvis_owner", "CREATE TABLE carvis.users (x int)", "RESET ROLE")
    result = run_alembic(migrator, "upgrade", HEAD)
    assert result.returncode != 0 and "carvis.users already exists" in result.stderr


# --- catalog check (doc 04 tests 1, 10, 13, 15) ----------------------------------------------------

@pytest.mark.parametrize("setup,code", [
    (["SET ROLE carvis_owner", "CREATE TABLE carvis.b2b1_t (workspace_id uuid)", "RESET ROLE"],
     "rls_not_forced:b2b1_t"),
    (["ALTER TABLE carvis.users NO FORCE ROW LEVEL SECURITY"], "rls_not_forced:users"),
    (["SET ROLE carvis_owner", "CREATE FUNCTION carvis.b2b1_f() RETURNS int LANGUAGE sql AS 'SELECT 1'",
      "GRANT EXECUTE ON FUNCTION carvis.b2b1_f() TO PUBLIC", "RESET ROLE"], "public_or_issuer_routine"),
    (["SET ROLE carvis_owner", "CREATE FUNCTION carvis.b2b1_d() RETURNS int LANGUAGE sql SECURITY DEFINER "
      "AS 'SELECT 1'", "RESET ROLE"], "definer_not_allowed"),
    (["GRANT UPDATE (status) ON carvis.users TO carvis_provisioner"], "table_privileges:carvis_provisioner:users"),
    (["GRANT DELETE ON carvis.memberships TO carvis_app"], "table_privileges:carvis_app:memberships"),
    (["GRANT SELECT ON carvis.users TO carvis_bootstrap"], "table_privileges:carvis_bootstrap:users"),
    (["ALTER ROLE carvis_provisioner BYPASSRLS"], "role_attribute:carvis_provisioner:rolbypassrls"),
    (["ALTER ROLE carvis_app LOGIN"], "role_attribute:carvis_app:rolcanlogin"),
    (["GRANT CREATE ON SCHEMA carvis TO carvis_provisioner"], "definer_owner_create:carvis_provisioner"),
    (["GRANT CREATE ON SCHEMA carvis_migrations TO carvis_provisioner"],
     "definer_owner_create:carvis_provisioner:carvis_migrations"),
    (["ALTER FUNCTION carvis.ensure_principal(text,text,text) SET search_path = public, pg_temp"],
     "definer_search_path"),
    (["ALTER FUNCTION carvis.ensure_principal(text,text,text) RESET search_path"], "definer_search_path"),
    (["CREATE ROLE rv_b2b1_admin LOGIN",
      "GRANT carvis_provisioner TO rv_b2b1_admin WITH ADMIN TRUE, INHERIT FALSE, SET FALSE"],
     "definer_owner_member:carvis_provisioner:rv_b2b1_admin"),
    (["CREATE ROLE rv_b2b1_admin2 LOGIN CREATEROLE",
      "GRANT carvis_provisioner TO rv_b2b1_admin2 WITH ADMIN TRUE, INHERIT FALSE, SET FALSE"],
     "definer_owner_members:carvis_provisioner"),
    (["SET ROLE carvis_owner", "CREATE FUNCTION carvis.b2b1_o() RETURNS int LANGUAGE sql AS 'SELECT 1'",
      "REVOKE ALL ON FUNCTION carvis.b2b1_o() FROM PUBLIC", "RESET ROLE",
      "ALTER FUNCTION carvis.b2b1_o() OWNER TO carvis_app"], "role_owns_routine:carvis_app:carvis.b2b1_o()"),
    (["CREATE TYPE carvis.b2b1_e AS ENUM ('x')", "REVOKE ALL ON TYPE carvis.b2b1_e FROM PUBLIC",
      "ALTER TYPE carvis.b2b1_e OWNER TO carvis_worker"], "role_owns_type:carvis_worker"),
    (["GRANT carvis_provisioner TO postgres"], "definer_owner_member:carvis_provisioner:postgres"),
    (["GRANT USAGE ON TYPE carvis.workspaces TO PUBLIC"], "public_or_issuer_type"),
    (["GRANT EXECUTE ON FUNCTION carvis.uuid_v7() TO carvis_app"], "routine_acl:carvis.uuid_v7()"),
])
def test_catalog_check_detects_violations(scratch, head, setup, code):
    assert violations(scratch.db_admin) == []
    try:
        _sql(scratch.db_admin, *setup)
        assert any(item.startswith(code) for item in violations(scratch.db_admin)), violations(scratch.db_admin)
    finally:
        _sql(scratch.admin, "DROP ROLE IF EXISTS rv_b2b1_admin", "DROP ROLE IF EXISTS rv_b2b1_admin2")


def test_catalog_does_not_depend_on_the_callers_search_path(scratch, head):
    """regprocedure output drops the schema when carvis is on the path; signatures must not."""
    assert violations(scratch.db_admin, search_path="carvis, public") == []
    _sql(scratch.db_admin, "GRANT EXECUTE ON FUNCTION carvis.uuid_v7() TO carvis_app")
    assert "routine_acl:carvis.uuid_v7()" in violations(scratch.db_admin, search_path="carvis, public")


def test_catalog_covers_the_migrations_schema(scratch, head):
    _sql(scratch.db_admin, "CREATE FUNCTION carvis_migrations.b2b1_m() RETURNS int LANGUAGE sql AS 'SELECT 1'")
    assert any(v.startswith("public_or_issuer_routine_null_acl:carvis_migrations.b2b1_m")
               for v in violations(scratch.db_admin))


def test_runtime_roles_are_not_owners_or_bypassrls(scratch, head):
    rows = _sql(scratch.db_admin, "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN "
                                  "('carvis_app', 'carvis_worker', 'carvis_bootstrap', 'carvis_provisioner')", fetch=True)
    assert all(not superuser and not bypass for _, superuser, bypass in rows) and len(rows) == 4
    owners = _sql(scratch.db_admin, "SELECT DISTINCT pg_get_userbyid(relowner) FROM pg_class c JOIN pg_namespace n "
                                    "ON n.oid = c.relnamespace WHERE n.nspname = 'carvis'", fetch=True)
    assert owners == [("carvis_owner",)]


# --- ensure_principal (doc 04 test 14) -------------------------------------------------------------

def test_first_and_repeat_calls_converge(scratch, login):
    columns, first, leftover = ensure(login, "user-a")
    assert columns == ["user_id", "status"] and first[1] == "active"
    assert leftover == ("", "", "")
    _, again, _ = ensure(login, "user-a", email="changed@example.test")
    assert again == first and counts(scratch.db_admin) == (1, 1, 1)
    email = _sql(scratch.db_admin, "SELECT email FROM carvis.users", fetch=True)
    assert email == [("tech@example.test",)], "email is written only on creation"
    workspace = _sql(scratch.db_admin, "SELECT kind, personal_owner_user_id FROM carvis.workspaces", fetch=True)
    member = _sql(scratch.db_admin, "SELECT user_id, role FROM carvis.memberships", fetch=True)
    assert workspace == [("personal", first[0])] and member == [(first[0], "owner")]


def test_calls_for_one_principal_leave_others_unchanged(scratch, login):
    ensure(login, "user-b")
    snapshot = {t: _sql(scratch.db_admin, f"SELECT * FROM carvis.{t} ORDER BY 1", fetch=True)
                for t in ("users", "workspaces", "memberships")}
    ensure(login, "user-a")
    ensure(login, "user-a")
    for table, rows in snapshot.items():
        current = _sql(scratch.db_admin, f"SELECT * FROM carvis.{table} ORDER BY 1", fetch=True)
        assert all(row in current for row in rows), table
    assert counts(scratch.db_admin) == (2, 2, 2)


def test_non_active_user_gets_nothing_new_and_settings_are_cleared(scratch, login):
    _sql(scratch.db_admin, f"INSERT INTO carvis.users (auth_issuer, auth_subject, status) VALUES ('{ISSUER}', 'user-d', 'deleting')")
    _, row, leftover = ensure(login, "user-d")
    assert row[1] == "deleting" and leftover == ("", "", "")
    assert counts(scratch.db_admin) == (1, 0, 0)


@pytest.mark.parametrize("issuer,subject,email", [
    (None, "s", None), (ISSUER, None, None), ("", "s", None), (ISSUER, "", None),
    ("x" * 256, "s", None), (ISSUER, "s" * 256, None), (ISSUER, "s", "e" * 321),
])
def test_invalid_inputs_are_refused(scratch, login, issuer, subject, email):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        ensure(login, subject, email=email, issuer=issuer)
    assert counts(scratch.db_admin) == (0, 0, 0)


def test_nul_cannot_reach_the_function(scratch, login):
    with pytest.raises((psycopg.DataError, ValueError)):
        ensure(login, "a\x00b")
    assert counts(scratch.db_admin) == (0, 0, 0)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_only_read_committed_is_accepted(scratch, login, isolation):
    with pytest.raises(psycopg.errors.InvalidTransactionState):
        ensure(login, "user-a", isolation=isolation)
    assert counts(scratch.db_admin) == (0, 0, 0)


def test_concurrent_first_requests_converge(scratch, login):
    results, errors, start = [], [], threading.Event()

    def call():
        start.wait()
        try:
            results.append(ensure(login, "user-c")[1])
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(repr(exc))

    threads = [threading.Thread(target=call) for _ in range(50)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(60)
    assert errors == [] and len(results) == 50
    assert len(set(results)) == 1 and counts(scratch.db_admin) == (1, 1, 1)


def test_search_path_hijack_has_no_effect(scratch, login):
    _sql(scratch.db_admin, "CREATE TABLE public.users (auth_issuer text, auth_subject text, email text)",
         "GRANT ALL ON public.users TO PUBLIC",
         "CREATE FUNCTION public.set_config(text, text, boolean) RETURNS text LANGUAGE sql AS 'SELECT ''x'''",
         "GRANT EXECUTE ON FUNCTION public.set_config(text, text, boolean) TO PUBLIC")
    with psycopg.connect(login) as conn:
        conn.execute("SET LOCAL search_path = public, pg_catalog")
        conn.execute("SET LOCAL ROLE carvis_bootstrap")
        conn.execute("SELECT * FROM carvis.ensure_principal(%s, %s, %s)", (ISSUER, "user-h", None)).fetchone()
    assert counts(scratch.db_admin) == (1, 1, 1)
    assert _sql(scratch.db_admin, "SELECT count(*) FROM public.users", fetch=True) == [(0,)]


def test_temp_schema_hijack_has_no_effect(scratch, login):
    with psycopg.connect(login) as conn:
        conn.execute("CREATE TEMP TABLE users (id uuid, status text, auth_issuer text, auth_subject text, email text)")
        conn.execute("CREATE TEMP TABLE workspaces (id uuid, kind text, name text, personal_owner_user_id uuid)")
        conn.execute("SET LOCAL search_path = pg_temp, pg_catalog")
        conn.execute("SET LOCAL ROLE carvis_bootstrap")
        conn.execute("SELECT * FROM carvis.ensure_principal(%s, %s, %s)", (ISSUER, "user-t", None)).fetchone()
        conn.execute("RESET ROLE")
        assert conn.execute("SELECT count(*) FROM pg_temp.users").fetchone() == (0,)
    assert counts(scratch.db_admin) == (1, 1, 1)


def test_provisioner_insert_without_bootstrap_settings_fails_with_check(scratch, two_users):
    """Doc 04 validation 2: with no bootstrap context, every provisioner insert fails WITH CHECK."""
    for statement in ("INSERT INTO carvis.users (auth_issuer, auth_subject) VALUES ('i', 's')",
                      "INSERT INTO carvis.workspaces (kind, name, personal_owner_user_id) "
                      f"VALUES ('personal', 'P', '{two_users['a']}')",
                      f"INSERT INTO carvis.memberships VALUES ('{two_users['wa']}', '{two_users['a']}', 'owner')"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            as_role(scratch.db_admin, "carvis_provisioner", [statement])


# --- database-level bounds, independent of the function body (doc 04 test 14) ----------------------

def _boot(user_id: str, subject: str = "user-a") -> dict[str, str]:
    return {"app.bootstrap_issuer": ISSUER, "app.bootstrap_subject": subject, "app.bootstrap_user_id": user_id}


@pytest.fixture
def two_users(scratch, login):
    a = ensure(login, "user-a")[1][0]
    b = ensure(login, "user-b")[1][0]
    wa, wb = (_sql(scratch.db_admin, f"SELECT id FROM carvis.workspaces WHERE personal_owner_user_id = '{u}'",
                   fetch=True)[0][0] for u in (a, b))
    return {"a": str(a), "b": str(b), "wa": str(wa), "wb": str(wb)}


def test_provisioner_cannot_add_an_owner_to_another_users_workspace(scratch, two_users):
    u = two_users
    for statement in (f"INSERT INTO carvis.memberships VALUES ('{u['wb']}', '{u['a']}', 'owner')",
                      f"INSERT INTO carvis.memberships VALUES ('{u['wa']}', '{u['b']}', 'owner')",
                      f"INSERT INTO carvis.memberships VALUES ('{u['wa']}', '{u['a']}', 'member')"):
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)):
            as_role(scratch.db_admin, "carvis_provisioner", [statement], _boot(u["a"]))
    assert counts(scratch.db_admin) == (2, 2, 2)


def test_provisioner_reads_only_the_bound_principal(scratch, two_users):
    rows = as_role(scratch.db_admin, "carvis_provisioner", ["SELECT id FROM carvis.users"], _boot(two_users["a"]),
                   fetch=True)
    assert [str(r[0]) for r in rows] == [two_users["a"]]


@pytest.mark.parametrize("statement", [
    "UPDATE carvis.users SET status = 'deleted'", "DELETE FROM carvis.memberships", "TRUNCATE carvis.users",
    "UPDATE carvis.workspaces SET name = 'x'", "DELETE FROM carvis.workspaces", "SELECT email FROM carvis.users",
    "SELECT name FROM carvis.workspaces", "SELECT created_at FROM carvis.memberships",
])
def test_provisioner_has_no_other_privileges(scratch, two_users, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_role(scratch.db_admin, "carvis_provisioner", [statement], _boot(two_users["a"]))


def test_trigger_rejects_non_owner_personal_membership_even_for_superuser(scratch, two_users):
    u = two_users
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(scratch.db_admin, f"INSERT INTO carvis.memberships VALUES ('{u['wa']}', '{u['b']}', 'member')")
    _sql(scratch.db_admin, "INSERT INTO carvis.workspaces (kind, name) VALUES ('shop', 'Shop')")
    shop = _sql(scratch.db_admin, "SELECT id FROM carvis.workspaces WHERE kind = 'shop'", fetch=True)[0][0]
    _sql(scratch.db_admin, f"INSERT INTO carvis.memberships VALUES ('{shop}', '{u['b']}', 'member')")
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(scratch.db_admin, f"UPDATE carvis.workspaces SET personal_owner_user_id = '{u['b']}' WHERE id = '{u['wa']}'")


def test_trigger_fails_closed_when_the_workspace_is_invisible(scratch, two_users):
    """The owner role has no policy under FORCE RLS, so its insert is refused (by RLS, before the
    trigger runs; the trigger's own branch is proven by the throwaway-role test below)."""
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InsufficientPrivilege)):
        as_role(scratch.db_admin, "carvis_owner",
                [f"INSERT INTO carvis.memberships VALUES ('{two_users['wa']}', '{two_users['a']}', 'owner')"])


# --- every reachable workspace has an owner (owner decision 2026-11-24) -----------------------------

@pytest.mark.parametrize("role", ["carvis_app", "carvis_worker", "carvis_bootstrap", "carvis_provisioner"])
def test_no_runtime_role_can_create_a_shop_or_change_memberships(scratch, two_users, role):
    for table, privilege in (("workspaces", "UPDATE"), ("workspaces", "DELETE"), ("memberships", "UPDATE"),
                             ("memberships", "DELETE"), ("users", "DELETE")):
        assert _sql(scratch.db_admin, f"SELECT has_table_privilege('{role}', 'carvis.{table}', '{privilege}')",
                    fetch=True) == [(False,)], (role, table, privilege)
    with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)):
        as_role(scratch.db_admin, role, ["INSERT INTO carvis.workspaces (kind, name) VALUES ('shop', 'Shop')"],
                _boot(two_users["a"]))


def test_every_provisioned_workspace_has_its_owner(scratch, two_users):
    ownerless = _sql(scratch.db_admin, "SELECT w.id FROM carvis.workspaces w WHERE NOT EXISTS (SELECT 1 FROM "
                                       "carvis.memberships m WHERE m.workspace_id = w.id AND m.role = 'owner')",
                     fetch=True)
    assert ownerless == []


# --- RLS for the runtime roles (doc 04 tests 1, 2, 6, 7, 8) -----------------------------------------

def _tenant(u: dict, who: str) -> dict[str, str]:
    return {"app.user_id": u[who], "app.workspace_ids": "{" + u["w" + who] + "}"}


@pytest.mark.parametrize("role", ["carvis_app", "carvis_worker"])
def test_no_context_means_no_rows(scratch, two_users, role):
    for table in ("users", "workspaces", "memberships"):
        assert as_role(scratch.db_admin, role, [f"SELECT * FROM carvis.{table}"], fetch=True) == []


@pytest.mark.parametrize("role", ["carvis_app", "carvis_worker"])
def test_unfiltered_queries_return_only_the_callers_rows(scratch, two_users, role):
    u = two_users
    for who, other in (("a", "b"), ("b", "a")):
        users = as_role(scratch.db_admin, role, ["SELECT id FROM carvis.users"], _tenant(u, who), fetch=True)
        workspaces = as_role(scratch.db_admin, role, ["SELECT id FROM carvis.workspaces"], _tenant(u, who), fetch=True)
        members = as_role(scratch.db_admin, role, ["SELECT workspace_id FROM carvis.memberships"], _tenant(u, who),
                          fetch=True)
        assert [str(r[0]) for r in users] == [u[who]]
        assert [str(r[0]) for r in workspaces] == [u["w" + who]]
        assert [str(r[0]) for r in members] == [u["w" + who]]


def test_malformed_context_raises_instead_of_matching(scratch, two_users):
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        as_role(scratch.db_admin, "carvis_app", ["SELECT * FROM carvis.users"], {"app.user_id": "not-a-uuid"},
                fetch=True)


def test_runtime_roles_cannot_insert(scratch, two_users):
    for role in ("carvis_app", "carvis_worker"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            as_role(scratch.db_admin, role,
                    [f"INSERT INTO carvis.users (auth_issuer, auth_subject) VALUES ('{ISSUER}', 'x')"],
                    _tenant(two_users, "a"))


def test_membership_revocation_applies_on_the_next_transaction(scratch, two_users):
    u = two_users
    before = as_role(scratch.db_admin, "carvis_app", ["SELECT workspace_id FROM carvis.memberships"],
                     {"app.user_id": u["a"]}, fetch=True)
    assert len(before) == 1
    _sql(scratch.db_admin, "ALTER TABLE carvis.memberships DISABLE TRIGGER memberships_personal_owner_check",
         f"DELETE FROM carvis.memberships WHERE user_id = '{u['a']}'")
    after = as_role(scratch.db_admin, "carvis_app", ["SELECT workspace_id FROM carvis.memberships"],
                    {"app.user_id": u["a"]}, fetch=True)
    assert after == []


def test_membership_lookup_by_user_uses_its_index(scratch, two_users):
    plan = as_role(scratch.db_admin, "carvis_app", ["SET LOCAL enable_seqscan = off",
                                                    "EXPLAIN SELECT workspace_id FROM carvis.memberships"],
                   {"app.user_id": two_users["a"]}, fetch=True)
    assert "memberships_user_id_idx" in " ".join(r[0] for r in plan)


# --- raw login and bootstrap (doc 04 tests 12, 13) ---------------------------------------------------

def test_raw_login_is_denied_every_identity_object(scratch, two_users, login):
    for statement in ("SELECT * FROM carvis.users", "SELECT * FROM carvis.workspaces",
                      "SELECT * FROM carvis.memberships", "SELECT carvis.uuid_v7()",
                      f"SELECT * FROM carvis.ensure_principal('{ISSUER}', 'x', NULL)"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(login, statement)


def test_bootstrap_can_only_execute_ensure_principal(scratch, two_users, login):
    for statement in ("SELECT * FROM carvis.users", "SELECT * FROM carvis.workspaces",
                      "SELECT * FROM carvis.memberships", "SELECT carvis.uuid_v7()"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            as_role(login, "carvis_bootstrap", [statement])
    for role in ("carvis_app", "carvis_worker", "public"):
        assert _sql(scratch.db_admin, f"SELECT has_function_privilege('{role}', "
                                      "'carvis.ensure_principal(text,text,text)', 'EXECUTE')", fetch=True) == [(False,)]


def test_issuer_roles_get_nothing_on_identity_objects(scratch, migrator):
    _sql(scratch.admin, "CREATE ROLE anon NOLOGIN", "CREATE ROLE authenticated NOLOGIN",
         "CREATE ROLE service_role NOLOGIN")
    try:
        ok(run_alembic(migrator, "upgrade", HEAD))
        assert violations(scratch.db_admin) == []
        for role in ("anon", "authenticated", "service_role"):
            assert _sql(scratch.db_admin, f"SELECT has_function_privilege('{role}', "
                                          "'carvis.ensure_principal(text,text,text)', 'EXECUTE'), "
                                          f"has_table_privilege('{role}', 'carvis.users', 'SELECT')",
                        fetch=True) == [(False, False)]
    finally:
        ok(run_alembic(migrator, "downgrade", B2A_HEAD))
        for role in ("anon", "authenticated", "service_role"):
            _sql(scratch.admin, f"DROP ROLE IF EXISTS {role}")


# --- uuid_v7 ------------------------------------------------------------------------------------

def test_uuid_v7_layout_and_time_order(scratch, head):
    values = []
    for _ in range(5):
        values.append(uuid.UUID(str(_sql(scratch.db_admin, "SELECT carvis.uuid_v7()", fetch=True)[0][0])))
        time.sleep(0.003)
    now_ms = int(time.time() * 1000)
    for value in values:
        assert value.version == 7 and value.variant == uuid.RFC_4122
        assert abs((value.int >> 80) - now_ms) < 60_000
    assert values == sorted(values), "calls in different milliseconds are time-ordered"


# --- guards that sit behind other layers (each mutation-tested on its own) --------------------------

def test_explicit_revokes_hold_even_if_default_privileges_drifted(scratch, migrator):
    """The default-privilege revokes from 0003 are one layer; 0004's explicit revokes are another."""
    ok(run_alembic(migrator, "upgrade", B2A_HEAD))
    _sql(scratch.db_admin, "ALTER DEFAULT PRIVILEGES FOR ROLE carvis_owner GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
         "ALTER DEFAULT PRIVILEGES FOR ROLE carvis_provisioner GRANT EXECUTE ON FUNCTIONS TO PUBLIC")
    try:
        ok(run_alembic(migrator, "upgrade", HEAD))
        for routine in ("carvis.uuid_v7()", "carvis.ensure_principal(text,text,text)",
                        "carvis.memberships_personal_owner_check()", "carvis.workspaces_owner_immutable()"):
            assert _sql(scratch.db_admin, f"SELECT has_function_privilege('public', '{routine}', 'EXECUTE')",
                        fetch=True) == [(False,)], routine
    finally:
        ok(run_alembic(migrator, "downgrade", B2A_HEAD))
        _sql(scratch.db_admin, "ALTER DEFAULT PRIVILEGES FOR ROLE carvis_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
             "ALTER DEFAULT PRIVILEGES FOR ROLE carvis_provisioner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")


def test_trigger_refuses_a_workspace_the_inserting_role_cannot_see(scratch, two_users):
    """No B2b-1 role can reach this branch (policies stop it first), so a throwaway role with an
    INSERT policy but no workspace visibility proves the trigger itself fails closed."""
    _sql(scratch.admin, "CREATE ROLE b1_other NOLOGIN")
    try:
        _sql(scratch.db_admin, "GRANT USAGE ON SCHEMA carvis TO b1_other",
             "GRANT INSERT ON carvis.memberships TO b1_other", "GRANT SELECT ON carvis.workspaces TO b1_other",
             "CREATE POLICY b2b1_test_insert ON carvis.memberships FOR INSERT TO b1_other WITH CHECK (true)")
        with pytest.raises(psycopg.errors.CheckViolation, match="workspace not visible"):
            as_role(scratch.db_admin, "b1_other",
                    [f"INSERT INTO carvis.memberships VALUES ('{two_users['wb']}', '{two_users['a']}', 'member')"])
    finally:
        _sql(scratch.db_admin, "DROP POLICY IF EXISTS b2b1_test_insert ON carvis.memberships",
             "REVOKE ALL ON carvis.memberships FROM b1_other", "REVOKE ALL ON carvis.workspaces FROM b1_other",
             "REVOKE ALL ON SCHEMA carvis FROM b1_other")


def test_migration_post_condition_refuses_a_violating_catalog(scratch, migrator):
    """A violation the preflight does not look for (a NULL-ACL routine in carvis_migrations) must stop
    the upgrade through the catalog post-condition, leaving nothing behind."""
    ok(run_alembic(migrator, "upgrade", B2A_HEAD))
    _sql(scratch.db_admin, "CREATE FUNCTION carvis_migrations.b2b1_m() RETURNS int LANGUAGE sql AS 'SELECT 1'")
    try:
        before = identity_catalog(scratch.db_admin)
        result = run_alembic(migrator, "upgrade", HEAD)
        assert result.returncode != 0 and "Catalog check failed" in result.stderr, result.stderr[-1500:]
        assert identity_catalog(scratch.db_admin) == before
    finally:
        _sql(scratch.db_admin, "DROP FUNCTION carvis_migrations.b2b1_m()")
