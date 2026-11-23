"""M2 B2a: the runtime login (doc 04 "Roles", test 12) and readiness's role switch, on real PostgreSQL 16.

Same server requirements as ``test_b1_migrations.py``. The runtime login is created by the test
superuser, as a deployment would, and granted with ``python -m db.runtime_login grant``.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import psycopg
import pytest

from db.readiness import DATABASE_MISCONFIGURED, MIGRATIONS_PENDING, READY, ReadinessProbe, postgres_fetch
from tests.test_b1_migrations import BACKEND, B1_HEAD, PASSWORD, _sql, admin_url, scratch  # noqa: F401
from tests.test_b2a_migrations import HEAD, MIGRATOR, members_of, migrator, ok, run_alembic  # noqa: F401

RUNTIME = "b1_runtime"


def runtime_login(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CARVIS_")}
    env.update(CARVIS_MIGRATION_DATABASE_URL=url, PYTHON_DOTENV_DISABLED="1")
    result = subprocess.run([sys.executable, "-m", "db.runtime_login", *args], cwd=BACKEND, env=env,
                            capture_output=True, text=True, timeout=60)
    assert PASSWORD not in result.stdout + result.stderr
    return result


@pytest.fixture
def migrated(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD))
    return migrator


@pytest.fixture
def runtime(scratch):
    return scratch.login(RUNTIME)


def readiness(url: str, enforce: bool = True) -> str:
    probe = ReadinessProbe(HEAD, postgres_fetch(url, enforce_login=enforce), 3.0)
    return asyncio.run(probe.check()).reason


# --- grant / check -------------------------------------------------------------------------------

def test_grant_then_check_with_exact_memberships(scratch, migrated, runtime):
    result = runtime_login(migrated, "grant", RUNTIME)
    assert result.returncode == 0, result.stderr
    assert runtime_login(migrated, "check", RUNTIME).returncode == 0
    assert runtime_login(migrated, "grant", RUNTIME).returncode == 0, "grant is idempotent"
    rows = _sql(scratch.db_admin, "SELECT r.rolname, a.admin_option, a.inherit_option, a.set_option "
                                  "FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid "
                                  f"JOIN pg_roles m ON m.oid = a.member WHERE m.rolname = '{RUNTIME}' ORDER BY 1",
                fetch=True)
    assert rows == [("carvis_app", False, False, True), ("carvis_bootstrap", False, False, True)]
    # Never a member of the definer owner, in any form.
    assert all(row[0] != RUNTIME for row in members_of(scratch.db_admin, "carvis_provisioner"))


def test_check_fails_before_grant(migrated, runtime):
    result = runtime_login(migrated, "check", RUNTIME)
    assert result.returncode == 1
    assert "missing_membership_carvis_app" in result.stderr and "missing_membership_carvis_bootstrap" in result.stderr


@pytest.mark.parametrize("setup,condition", [
    ([f"ALTER ROLE {RUNTIME} SUPERUSER"], "superuser"),
    ([f"ALTER ROLE {RUNTIME} BYPASSRLS"], "bypassrls"),
    ([f"ALTER ROLE {RUNTIME} CREATEROLE"], "createrole"),
    ([f"ALTER ROLE {RUNTIME} CREATEDB"], "createdb"),
    ([f"ALTER ROLE {RUNTIME} REPLICATION"], "replication"),
    ([f"ALTER ROLE {RUNTIME} NOLOGIN"], "nologin"),
    ([f"ALTER ROLE {RUNTIME} SET search_path = public"], "role_settings"),
    (["CREATE TABLE public.b2a_rt (a int)", f"ALTER TABLE public.b2a_rt OWNER TO {RUNTIME}"], "owns_objects"),
    (["CREATE TABLE public.b2a_rt (a int)", f"GRANT SELECT (a) ON public.b2a_rt TO {RUNTIME}"], "acl_entries"),
    ([f"GRANT CREATE ON SCHEMA public TO {RUNTIME}"], "acl_entries"),
    ([f"ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO {RUNTIME}"], "default_acl"),
    (["GRANT pg_read_all_data TO " + RUNTIME], "unexpected_membership"),
    ([f"GRANT carvis_app TO {RUNTIME}"], "unexpected_membership"),  # INHERIT TRUE
    ([f"GRANT carvis_provisioner TO {RUNTIME} WITH INHERIT FALSE, SET TRUE"], "unexpected_membership"),
    (["CREATE ROLE b1_other LOGIN", f"GRANT {RUNTIME} TO b1_other"], "has_members"),
])
def test_each_refusal_condition(scratch, migrated, runtime, setup, condition):
    try:
        _sql(scratch.db_admin, *setup)
        for command in ("grant", "check"):
            result = runtime_login(migrated, command, RUNTIME)
            assert result.returncode == 1 and condition in result.stderr, (command, result.stderr)
        # A refused grant grants nothing.
        assert not [row for row in members_of(scratch.db_admin, "carvis_bootstrap") if row[0] == RUNTIME]
    finally:
        _sql(scratch.db_admin, "DROP TABLE IF EXISTS public.b2a_rt", f"REVOKE CREATE ON SCHEMA public FROM {RUNTIME}",
             f"ALTER DEFAULT PRIVILEGES REVOKE SELECT ON TABLES FROM {RUNTIME}")


def test_database_owner_is_refused(scratch, migrated, runtime):
    """Owning the database implies pg_database_owner membership with no pg_auth_members row."""
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO {RUNTIME}")
    try:
        result = runtime_login(migrated, "check", RUNTIME)
        assert result.returncode == 1 and "owns_objects" in result.stderr
    finally:
        _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO {MIGRATOR}")


def test_duplicate_membership_rows_are_refused(scratch, migrated, runtime):
    ok_grant = runtime_login(migrated, "grant", RUNTIME)
    assert ok_grant.returncode == 0
    _sql(scratch.admin, f"GRANT carvis_app TO {RUNTIME} WITH INHERIT FALSE, SET TRUE GRANTED BY postgres")
    result = runtime_login(migrated, "check", RUNTIME)
    assert result.returncode == 1 and "duplicate_membership_carvis_app" in result.stderr


@pytest.mark.parametrize("name", ["carvis_app", "Bad-Name", "x" * 64, "a;drop", ""])
def test_bad_login_names_are_usage_errors(migrated, name):
    assert runtime_login(migrated, "check", name).returncode == 2


def test_missing_url_is_a_usage_error():
    result = runtime_login("", "check", RUNTIME)
    assert result.returncode == 2 and "CARVIS_MIGRATION_DATABASE_URL" in result.stderr


def test_before_0003_the_check_names_missing_roles(scratch, migrator, runtime):
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    result = runtime_login(migrator, "grant", RUNTIME)
    assert result.returncode == 1 and "missing_role_carvis_bootstrap" in result.stderr


# --- Raw login has no access (doc 04 test 12) -----------------------------------------------------

def test_raw_login_is_denied_every_carvis_object(scratch, migrated, runtime):
    assert runtime_login(migrated, "grant", RUNTIME).returncode == 0
    _sql(scratch.db_admin, "SET ROLE carvis_owner",
         "CREATE TABLE carvis.b2a_t (a int)", "CREATE SEQUENCE carvis.b2a_s",
         "CREATE FUNCTION carvis.b2a_f() RETURNS int LANGUAGE sql AS 'SELECT 1'",
         "GRANT SELECT ON carvis.b2a_t TO carvis_app", "GRANT EXECUTE ON FUNCTION carvis.b2a_f() TO carvis_app",
         "RESET ROLE")
    try:
        statements = ["SELECT * FROM carvis.b2a_t", "INSERT INTO carvis.b2a_t VALUES (1)",
                      "SELECT nextval('carvis.b2a_s')", "SELECT carvis.b2a_f()",
                      "SELECT * FROM carvis_migrations.alembic_version"]
        for statement in statements:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                _sql(runtime, statement)
        # With SET ROLE carvis_app it gets exactly carvis_app's grants.
        with psycopg.connect(runtime) as conn:
            conn.execute("SET LOCAL ROLE carvis_app")
            assert conn.execute("SELECT version_num FROM carvis_migrations.alembic_version").fetchone() == (HEAD,)
            assert conn.execute("SELECT carvis.b2a_f()").fetchone() == (1,)
        with psycopg.connect(runtime) as conn:
            conn.execute("SET LOCAL ROLE carvis_bootstrap")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT * FROM carvis.b2a_t")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(runtime, "SET ROLE carvis_provisioner")
    finally:
        _sql(scratch.db_admin, "DROP TABLE carvis.b2a_t", "DROP SEQUENCE carvis.b2a_s", "DROP FUNCTION carvis.b2a_f()")


# --- Readiness role switch and self-check -----------------------------------------------------------

def test_readiness_ready_for_a_compliant_login(migrated, runtime):
    assert runtime_login(migrated, "grant", RUNTIME).returncode == 0
    assert readiness(runtime) == READY
    # The INHERIT FALSE login can read the version table only through SET LOCAL ROLE carvis_app.
    assert readiness(runtime, enforce=False) == READY


def test_readiness_before_migration_is_pending(scratch, migrator, runtime):
    assert readiness(runtime) == MIGRATIONS_PENDING
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    assert readiness(runtime) == MIGRATIONS_PENDING  # carvis_bootstrap not created yet


def test_readiness_refuses_unsafe_logins_under_enforcement(scratch, migrated, runtime):
    assert readiness(scratch.db_admin) == DATABASE_MISCONFIGURED, "superuser"
    assert readiness(runtime) == DATABASE_MISCONFIGURED, "not a member yet"
    assert runtime_login(migrated, "grant", RUNTIME).returncode == 0
    _sql(scratch.admin, f"ALTER ROLE {RUNTIME} BYPASSRLS")
    assert readiness(runtime) == DATABASE_MISCONFIGURED, "bypassrls"
    _sql(scratch.admin, f"ALTER ROLE {RUNTIME} NOBYPASSRLS")
    assert readiness(runtime) == READY


def test_readiness_without_enforcement_still_switches_role(scratch, migrated, runtime):
    assert readiness(scratch.db_admin, enforce=False) == READY  # local superuser
    assert readiness(runtime, enforce=False) == DATABASE_MISCONFIGURED  # cannot SET ROLE carvis_app


def test_from_settings_enforces_outside_local_only(scratch, migrated):
    from settings import Settings, normalize_database_url

    _, url = normalize_database_url(scratch.db_admin)
    for environment, expected in (("local", READY), ("production", DATABASE_MISCONFIGURED)):
        settings = Settings(environment=environment, database_status="configured", database_url=url)
        probe = ReadinessProbe.from_settings(settings, HEAD)
        try:
            assert asyncio.run(probe.check()).reason == expected, environment
        finally:
            asyncio.run(probe.close())


@pytest.mark.parametrize("statement,condition", [
    (f"CREATE TABLE b2a_other_t (a int); ALTER TABLE b2a_other_t OWNER TO {RUNTIME}", "owns_objects"),
    (f"CREATE TABLE b2a_other_t (a int); GRANT SELECT ON b2a_other_t TO {RUNTIME}", "acl_entries"),
])
def test_objects_in_another_database_are_refused(scratch, migrated, runtime, statement, condition):
    """Round-1 review: the check covers every database in the cluster, not only the CARVIS one."""
    from tests.test_b1_migrations import _url

    other = scratch.extra_database("postgres")
    _sql(_url(scratch.admin, database=other), *statement.split("; "))
    result = runtime_login(migrated, "grant", RUNTIME)
    assert result.returncode == 1 and condition in result.stderr, result.stderr
    assert not [row for row in members_of(scratch.db_admin, "carvis_app") if row[0] == RUNTIME]
    assert readiness(runtime, enforce=True) == DATABASE_MISCONFIGURED
