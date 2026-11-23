"""M2 B2a: revision 0003_runtime_roles against real PostgreSQL 16 (doc 04 "Roles", "Function privileges",
"Function ownership and migration membership").

Needs a **throwaway** PostgreSQL 16+ server whose superuser URL is in ``CARVIS_TEST_POSTGRES_URL``; the
tests create and drop databases and cluster-wide CARVIS roles. Without it they skip, unless
``CARVIS_REQUIRE_POSTGRES=1`` (CI), where they fail. Every migration below runs as a non-superuser
``CREATEROLE`` database owner unless the test says otherwise, because that is the only path that uses
PostgreSQL 16's automatic ADMIN grant and the temporary SET grant.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from db.roles import B2A_ROLES, MARKER_0003
from tests.test_b1_migrations import (ALEMBIC_INI, BACKEND, B1_HEAD, PASSWORD, _sql, admin_url, catalog,  # noqa: F401
                                      scratch)

HEAD = "0003_runtime_roles"
MIGRATOR = "b1_migrator"


def run_alembic(url: str, *args: str, **extra_env: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CARVIS_")}
    env.update(CARVIS_MIGRATION_DATABASE_URL=url, PYTHON_DOTENV_DISABLED="1", **extra_env)
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args], cwd=BACKEND,
                            env=env, capture_output=True, text=True, timeout=120)
    assert PASSWORD not in result.stdout + result.stderr, "a credential reached migration output"
    return result


def ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stderr[-2500:]


@pytest.fixture
def migrator(scratch):
    """A non-superuser CREATEROLE login that owns the scratch database; returns its URL."""
    url = scratch.login(MIGRATOR, "CREATEROLE")
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO {MIGRATOR}")
    return url


def full_catalog(url: str) -> dict:
    """B1's catalog plus default ACLs, the version and routine ACLs."""
    snapshot = catalog(url)
    snapshot["default_acl"] = _sql(url, "SELECT pg_get_userbyid(defaclrole), defaclnamespace, defaclobjtype, "
                                        "defaclacl::text FROM pg_default_acl ORDER BY 1, 3", fetch=True)
    snapshot["version"] = _sql(url, "SELECT version_num FROM carvis_migrations.alembic_version", fetch=True)
    return snapshot


def members_of(url: str, role: str) -> list[tuple]:
    return _sql(url, "SELECT m.rolname, g.rolname, a.admin_option, a.inherit_option, a.set_option "
                     "FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
                     f"JOIN pg_roles g ON g.oid = a.grantor WHERE r.rolname = '{role}' ORDER BY 1, 2", fetch=True)


# --- Success, PostgreSQL 16 membership behaviour -------------------------------------------------

def test_round_trip_as_non_superuser_createrole_login(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD))
    first = full_catalog(scratch.db_admin)
    roles = {row[0]: row for row in first["roles"]}
    for role in B2A_ROLES:
        assert roles[role][1:7] == (False, False, False, False, False, False), roles[role]  # NOLOGIN, no attributes
        assert roles[role][8] == MARKER_0003
        # PostgreSQL 16's automatic grant to the creating CREATEROLE login, and nothing else: no
        # temporary SET row survives and no self-grant was added.
        assert members_of(scratch.db_admin, role) == [(MIGRATOR, "postgres", True, False, False)]
    assert first["version"] == [(HEAD,)]
    defaults = {row[0]: row for row in first["default_acl"]}
    assert defaults["carvis_owner"][1:] == (0, "f", "{carvis_owner=X/carvis_owner}")
    assert defaults["carvis_provisioner"][1:] == (0, "f", "{carvis_provisioner=X/carvis_provisioner}")
    acl = {row[0]: row[2] for row in first["schemas"]}["carvis"]
    assert "carvis_bootstrap=U/carvis_owner" in acl and "carvis_provisioner=U/carvis_owner" in acl
    assert "carvis_provisioner=UC" not in acl and "carvis_bootstrap=UC" not in acl

    ok(run_alembic(migrator, "downgrade", B1_HEAD))
    down = full_catalog(scratch.db_admin)
    assert not {row[0] for row in down["roles"]} & set(B2A_ROLES)
    assert down["default_acl"] == []
    assert down["version"] == [(B1_HEAD,)]
    ok(run_alembic(migrator, "upgrade", HEAD))
    assert full_catalog(scratch.db_admin) == first, "upgrade → downgrade → upgrade must give an identical catalog"
    ok(run_alembic(migrator, "downgrade", "base"))
    assert not [row for row in catalog(scratch.db_admin)["roles"]], "base leaves no CARVIS role"


def test_round_trip_as_superuser_leaves_no_members(scratch):
    ok(run_alembic(scratch.db_admin, "upgrade", HEAD))
    for role in B2A_ROLES:
        assert members_of(scratch.db_admin, role) == []
    ok(run_alembic(scratch.db_admin, "downgrade", "base"))
    assert not catalog(scratch.db_admin)["roles"]


def test_admin_only_membership_cannot_set_role_or_change_defaults(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD))
    import psycopg

    for statement in ("SET ROLE carvis_provisioner",
                      "ALTER DEFAULT PRIVILEGES FOR ROLE carvis_provisioner GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
                      "SET ROLE carvis_bootstrap"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(migrator, statement)


def test_new_functions_get_no_public_execute_for_each_creating_role(scratch, migrator):
    """The global default revoke works for carvis_owner and carvis_provisioner (doc 04, test 15)."""
    ok(run_alembic(migrator, "upgrade", HEAD))
    _sql(scratch.db_admin,
         "SET ROLE carvis_owner",
         "CREATE FUNCTION carvis.b2a_owner_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'",
         "RESET ROLE",
         # The provisioner has no CREATE on carvis in B2a; grant it for this check and take it back.
         "GRANT CREATE ON SCHEMA carvis TO carvis_provisioner",
         "SET ROLE carvis_provisioner",
         "CREATE FUNCTION carvis.b2a_prov_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'",
         "RESET ROLE",
         "REVOKE CREATE ON SCHEMA carvis FROM carvis_provisioner")
    rows = dict(_sql(scratch.db_admin, "SELECT proname, proacl::text FROM pg_proc WHERE proname LIKE 'b2a_%_fn'",
                     fetch=True))
    assert rows == {"b2a_owner_fn": "{carvis_owner=X/carvis_owner}",
                    "b2a_prov_fn": "{carvis_provisioner=X/carvis_provisioner}"}
    public_can = _sql(scratch.db_admin, "SELECT has_function_privilege('public', 'carvis.b2a_owner_fn()', 'EXECUTE'),"
                                        " has_function_privilege('public', 'carvis.b2a_prov_fn()', 'EXECUTE')",
                      fetch=True)
    assert public_can == [(False, False)]
    _sql(scratch.db_admin, "DROP FUNCTION carvis.b2a_owner_fn()", "DROP FUNCTION carvis.b2a_prov_fn()")


def test_in_schema_revoke_alone_does_not_remove_public_execute(scratch):
    """Negative control for doc 04: the per-schema form cannot remove the global PUBLIC default."""
    _sql(scratch.db_admin, "CREATE SCHEMA b2a_ctl",
         "ALTER DEFAULT PRIVILEGES IN SCHEMA b2a_ctl REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
         "CREATE FUNCTION b2a_ctl.f() RETURNS int LANGUAGE sql AS 'SELECT 1'")
    assert _sql(scratch.db_admin, "SELECT has_function_privilege('public', 'b2a_ctl.f()', 'EXECUTE')",
                fetch=True) == [(True,)]


# --- Forced failure: nothing changes -------------------------------------------------------------

@pytest.mark.parametrize("step", ["create_roles", "owner_privileges", "temporary_grant", "provisioner_defaults",
                                  "issuer_revokes"])
def test_forced_failure_rolls_back_without_drift(scratch, migrator, step):
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    before = full_catalog(scratch.db_admin)
    result = run_alembic(migrator, "upgrade", HEAD, CARVIS_ENV="local", CARVIS_TEST_FAIL_AT=step)
    assert result.returncode != 0 and f"forced failure at {step}" in result.stderr
    assert full_catalog(scratch.db_admin) == before, "roles, memberships, ACLs, defaults and version unchanged"
    ok(run_alembic(migrator, "upgrade", HEAD))  # and the revision still applies afterwards


def test_forced_failure_in_downgrade_rolls_back(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD))
    before = full_catalog(scratch.db_admin)
    result = run_alembic(migrator, "downgrade", B1_HEAD, CARVIS_ENV="local", CARVIS_TEST_FAIL_AT="downgrade_defaults")
    assert result.returncode != 0
    assert full_catalog(scratch.db_admin) == before


def test_failure_hook_is_ignored_outside_local(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", HEAD, CARVIS_ENV="production", CARVIS_TEST_FAIL_AT="create_roles",
                   VAPI_WEBHOOK_SECRET="x"))


# --- Preflight refusals: nothing changes ---------------------------------------------------------

REFUSALS = [
    (["CREATE ROLE carvis_bootstrap NOLOGIN"], "carvis_bootstrap already exists"),
    (["CREATE ROLE carvis_provisioner NOLOGIN", f"COMMENT ON ROLE carvis_provisioner IS '{MARKER_0003}'"],
     "carvis_provisioner already exists"),
    (["ALTER ROLE carvis_app BYPASSRLS"], "carvis_app has gained LOGIN or an elevated attribute"),
    (["ALTER ROLE carvis_worker LOGIN"], "carvis_worker has gained LOGIN"),
    (["GRANT pg_read_all_data TO carvis_app"], "carvis_app is a member of another role"),
    (["CREATE ROLE b1_other LOGIN", "GRANT carvis_app TO b1_other"], "carvis_app has members other than"),
    (["ALTER ROLE carvis_app SET search_path = public"], "carvis_app has role-level settings"),
    (["ALTER DEFAULT PRIVILEGES FOR ROLE carvis_owner GRANT SELECT ON TABLES TO carvis_app"],
     "appears in a default ACL"),
    (["CREATE TABLE public.b2a_owned (a int)", "ALTER TABLE public.b2a_owned OWNER TO carvis_worker"],
     "carvis_worker owns or holds privileges"),
    (["CREATE TABLE public.b2a_col (a int)", "GRANT SELECT (a) ON public.b2a_col TO carvis_app"],
     "carvis_app owns or holds privileges"),
    (["GRANT CREATE ON SCHEMA public TO carvis_app"], "carvis_app owns or holds privileges"),
    (["CREATE ROLE anon NOLOGIN", "GRANT carvis_app TO anon"], "carvis_app has members other than"),
]


@pytest.mark.parametrize("setup,message", REFUSALS)
def test_preflight_refuses_without_modification(scratch, migrator, setup, message):
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    try:
        _sql(scratch.db_admin, *setup)
        before = full_catalog(scratch.db_admin)
        result = run_alembic(migrator, "upgrade", HEAD)
        assert result.returncode != 0 and message in result.stderr, result.stderr[-1500:]
        assert full_catalog(scratch.db_admin) == before
    finally:
        _sql(scratch.db_admin, "DROP TABLE IF EXISTS public.b2a_owned", "DROP TABLE IF EXISTS public.b2a_col",
             "REVOKE CREATE ON SCHEMA public FROM carvis_app")
        if _sql(scratch.admin, "SELECT 1 FROM pg_roles WHERE rolname = 'anon'", fetch=True):
            _sql(scratch.admin, "DROP ROLE anon")


def test_pinned_self_grant_setting_leaves_only_the_admin_grant(scratch, migrator):
    """A login-level createrole_self_grant cannot add SET/INHERIT rows to the 0003 roles."""
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    _sql(scratch.admin, f"ALTER ROLE {MIGRATOR} SET createrole_self_grant = 'set, inherit'")
    try:
        ok(run_alembic(migrator, "upgrade", HEAD))
        for role in B2A_ROLES:
            assert members_of(scratch.db_admin, role) == [(MIGRATOR, "postgres", True, False, False)]
    finally:
        _sql(scratch.admin, f"ALTER ROLE {MIGRATOR} RESET createrole_self_grant")


def test_self_grants_left_on_b1_roles_are_refused(scratch, migrator):
    """0002 never pinned the setting: its SET/INHERIT self-grants on runtime roles stop 0003 (fail closed)."""
    _sql(scratch.admin, f"ALTER ROLE {MIGRATOR} SET createrole_self_grant = 'set, inherit'")
    try:
        ok(run_alembic(migrator, "upgrade", B1_HEAD))
        before = full_catalog(scratch.db_admin)
        result = run_alembic(migrator, "upgrade", HEAD)
        assert result.returncode != 0 and "has members other than the migration login" in result.stderr
        assert full_catalog(scratch.db_admin) == before
    finally:
        _sql(scratch.admin, f"ALTER ROLE {MIGRATOR} RESET createrole_self_grant")


# --- Issuer roles --------------------------------------------------------------------------------

def test_issuer_role_grants_are_revoked_including_routines(scratch, migrator):
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    _sql(scratch.admin, "CREATE ROLE anon NOLOGIN", "CREATE ROLE authenticated NOLOGIN",
         "CREATE ROLE service_role NOLOGIN")
    try:
        _sql(scratch.db_admin,
             "SET ROLE carvis_owner",
             "CREATE TABLE carvis.b2a_hostile (a int)",
             "CREATE FUNCTION carvis.b2a_hf() RETURNS int LANGUAGE sql AS 'SELECT 1'",
             "CREATE PROCEDURE carvis.b2a_hp() LANGUAGE sql AS 'SELECT 1'",
             "RESET ROLE",
             "GRANT USAGE, CREATE ON SCHEMA carvis TO anon, authenticated, service_role",
             "GRANT ALL ON carvis.b2a_hostile TO anon, authenticated",
             "GRANT SELECT (a) ON carvis.b2a_hostile TO service_role",
             "GRANT EXECUTE ON FUNCTION carvis.b2a_hf() TO anon",
             "GRANT EXECUTE ON PROCEDURE carvis.b2a_hp() TO authenticated",
             "GRANT USAGE ON SCHEMA carvis_migrations TO anon",
             "GRANT SELECT ON carvis_migrations.alembic_version TO service_role")
        ok(run_alembic(migrator, "upgrade", HEAD))
        held = _sql(scratch.db_admin, """
            SELECT r.rolname, count(*) FROM pg_roles r CROSS JOIN LATERAL (
              SELECT 1 FROM pg_namespace n, aclexplode(n.nspacl) a WHERE n.nspname IN ('carvis', 'carvis_migrations')
                AND a.grantee = r.oid
              UNION ALL SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, aclexplode(c.relacl) a
                WHERE n.nspname IN ('carvis', 'carvis_migrations') AND a.grantee = r.oid
              UNION ALL SELECT 1 FROM pg_attribute t JOIN pg_class c ON c.oid = t.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace, aclexplode(t.attacl) a
                WHERE n.nspname IN ('carvis', 'carvis_migrations') AND a.grantee = r.oid
              UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace, aclexplode(p.proacl) a
                WHERE n.nspname IN ('carvis', 'carvis_migrations') AND a.grantee = r.oid) x
            WHERE r.rolname IN ('anon', 'authenticated', 'service_role') GROUP BY 1""", fetch=True)
        assert held == [], held
        for role in ("anon", "authenticated", "service_role"):
            assert _sql(scratch.db_admin, f"SELECT has_schema_privilege('{role}', 'carvis', 'USAGE'), "
                                          f"has_function_privilege('{role}', 'carvis.b2a_hf()', 'EXECUTE')",
                        fetch=True) == [(False, False)]
        _sql(scratch.db_admin, "DROP TABLE carvis.b2a_hostile", "DROP FUNCTION carvis.b2a_hf()",
             "DROP PROCEDURE carvis.b2a_hp()")
    finally:
        for role in ("anon", "authenticated", "service_role"):
            _sql(scratch.db_admin, f"REVOKE ALL ON SCHEMA carvis_migrations FROM {role}")
            _sql(scratch.admin, f"DROP ROLE IF EXISTS {role}")


def test_preexisting_public_function_execute_is_removed(scratch, migrator):
    """A routine created in carvis before 0003 (NULL ACL = PUBLIC EXECUTE) loses PUBLIC EXECUTE."""
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    _sql(scratch.db_admin, "SET ROLE carvis_owner",
         "CREATE FUNCTION carvis.b2a_old() RETURNS int LANGUAGE sql AS 'SELECT 1'", "RESET ROLE")
    ok(run_alembic(migrator, "upgrade", HEAD))
    assert _sql(scratch.db_admin, "SELECT has_function_privilege('public', 'carvis.b2a_old()', 'EXECUTE')",
                fetch=True) == [(False,)]
    _sql(scratch.db_admin, "DROP FUNCTION carvis.b2a_old()")


def test_grant_by_another_grantor_that_revoke_cannot_remove_stops_the_migration(scratch, migrator):
    """Post-condition: a privilege granted to an issuer role by a third role survives the owner's
    REVOKE, so the migration must refuse rather than report success."""
    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    _sql(scratch.admin, "CREATE ROLE anon NOLOGIN", "CREATE ROLE b1_other NOLOGIN")
    try:
        _sql(scratch.db_admin, "SET ROLE carvis_owner",
             "GRANT USAGE ON SCHEMA carvis TO b1_other WITH GRANT OPTION", "RESET ROLE",
             "SET ROLE b1_other", "GRANT USAGE ON SCHEMA carvis TO anon", "RESET ROLE")
        before = full_catalog(scratch.db_admin)
        result = run_alembic(migrator, "upgrade", HEAD)
        assert result.returncode != 0
        assert "still holds a privilege" in result.stderr or "owns or holds privileges" in result.stderr, \
            result.stderr[-1500:]
        assert full_catalog(scratch.db_admin) == before
    finally:
        _sql(scratch.db_admin, "REVOKE USAGE ON SCHEMA carvis FROM b1_other CASCADE")
        _sql(scratch.admin, "DROP ROLE IF EXISTS anon")


@pytest.mark.parametrize("statement", [
    "CREATE TABLE b2a_x (a int); ALTER TABLE b2a_x OWNER TO carvis_app",
    "CREATE TABLE b2a_x (a int); GRANT SELECT ON b2a_x TO carvis_worker",
    "CREATE TABLE b2a_x (a int); ALTER TABLE b2a_x OWNER TO carvis_owner",
])
def test_preflight_refuses_b1_role_objects_in_another_database(scratch, migrator, statement):
    """Round-1 review: ownership or privileges in another database of the cluster are refused too."""
    from tests.test_b1_migrations import _url

    ok(run_alembic(migrator, "upgrade", B1_HEAD))
    other = scratch.extra_database("postgres")
    _sql(_url(scratch.admin, database=other), *statement.split("; "))
    before = full_catalog(scratch.db_admin)
    result = run_alembic(migrator, "upgrade", HEAD)
    assert result.returncode != 0 and "owns or holds privileges" in result.stderr, result.stderr[-1500:]
    assert full_catalog(scratch.db_admin) == before
    _sql(_url(scratch.admin, database=other), "DROP TABLE b2a_x")
