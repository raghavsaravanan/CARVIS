"""M2 B1: Alembic chain, provider-neutral roles, schema ownership and real-PostgreSQL readiness.

The history tests need no database. The rest need a **throwaway** PostgreSQL 16+ server whose
superuser URL is in ``CARVIS_TEST_POSTGRES_URL`` (CI's service container, or a local container).
They create and drop databases and the cluster-wide CARVIS roles, so never point it at a real server.
Without the URL they skip, unless ``CARVIS_REQUIRE_POSTGRES=1`` (CI), where they fail instead.
Tests run serially: the CARVIS roles are cluster-wide.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from db.history import HistoryError, check_linear_history, script_directory
from db.readiness import DATABASE_UNREACHABLE, MIGRATIONS_PENDING, READY, ReadinessProbe, postgres_fetch
from db.roles import MARKER, ROLES

BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND / "migrations" / "alembic.ini"
ADMIN_URL = (os.getenv("CARVIS_TEST_POSTGRES_URL") or "").strip()
REQUIRED = os.getenv("CARVIS_REQUIRE_POSTGRES") == "1"
PASSWORD = "b1-scratch-Pw-7731"


# --- History (no database) ----------------------------------------------------------------------

def test_shipped_chain_is_linear_with_expected_head():
    assert check_linear_history(script_directory()) == "0002_roles"


def _write_tree(tmp_path: Path, revisions: dict[str, object]) -> ScriptDirectory:
    versions = tmp_path / "versions"
    versions.mkdir()
    (tmp_path / "script.py.mako").write_text("")
    for rev, down in revisions.items():
        (versions / f"{rev}.py").write_text(textwrap.dedent(f"""
            revision = {rev!r}
            down_revision = {down!r}
            branch_labels = None
            depends_on = None
            def upgrade(): pass
            def downgrade(): pass
        """))
    return ScriptDirectory(str(tmp_path))


def test_two_heads_are_rejected(tmp_path):
    with pytest.raises(HistoryError, match="exactly one Alembic head"):
        check_linear_history(_write_tree(tmp_path, {"a": None, "b": "a", "c": "a"}))


def test_merge_revision_is_rejected(tmp_path):
    with pytest.raises(HistoryError, match="merge point|branch point"):
        check_linear_history(_write_tree(tmp_path, {"a": None, "b": "a", "c": "a", "d": ("b", "c")}))


def test_two_bases_are_rejected(tmp_path):
    with pytest.raises(HistoryError):
        check_linear_history(_write_tree(tmp_path, {"a": None, "b": None, "c": ("a", "b")}))


def test_history_cli_exit_status():
    ok = subprocess.run([sys.executable, "-m", "db.history"], cwd=BACKEND, capture_output=True, text=True)
    assert ok.returncode == 0 and "0002_roles" in ok.stdout


# --- Real PostgreSQL ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def admin_url():
    if not ADMIN_URL:
        if REQUIRED:
            pytest.fail("CARVIS_REQUIRE_POSTGRES=1 but CARVIS_TEST_POSTGRES_URL is not set")
        pytest.skip("CARVIS_TEST_POSTGRES_URL not set (real-PostgreSQL tests skipped; reported as skipped)")
    import psycopg

    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3) as conn:
            version = conn.execute("SHOW server_version_num").fetchone()[0]
    except psycopg.OperationalError:
        if REQUIRED:
            pytest.fail("CARVIS_TEST_POSTGRES_URL is unreachable")
        pytest.skip("CARVIS_TEST_POSTGRES_URL is unreachable")
    assert int(version) >= 160000, "PostgreSQL 16 or later is required"
    return ADMIN_URL


def _url(base: str, user: str | None = None, password: str | None = None, database: str | None = None) -> str:
    from sqlalchemy.engine import make_url

    url = make_url(base)
    if user is not None:
        url = url.set(username=user, password=password)
    if database is not None:
        url = url.set(database=database)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _sql(url: str, *statements: str, fetch: bool = False):
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        result = None
        for statement in statements:
            cursor = conn.execute(statement)
            if fetch:
                result = cursor.fetchall()
        return result


TEST_LOGINS = ("b1_migrator", "b1_plain", "b1_runtime", "b1_other", "b1_noowner")


def _drop_cluster_objects(admin: str) -> None:
    for role in (*TEST_LOGINS, *ROLES):
        exists = _sql(admin, f"SELECT 1 FROM pg_roles WHERE rolname = '{role}'", fetch=True)
        if exists:
            _sql(admin, f"DROP ROLE {role}")


@pytest.fixture
def scratch(admin_url):
    """A fresh database; all CARVIS roles and test logins are removed before and after."""
    name = f"carvis_b1_{uuid.uuid4().hex[:10]}"
    databases = [name]
    _drop_cluster_objects(admin_url)
    _sql(admin_url, f"CREATE DATABASE {name}")

    class Scratch:
        admin = admin_url
        database = name
        db_admin = _url(admin_url, database=name)

        def login(self, user, attributes=""):
            _sql(admin_url, f"CREATE ROLE {user} LOGIN PASSWORD '{PASSWORD}' {attributes}")
            return _url(admin_url, user, PASSWORD, name)

        def extra_database(self, owner):
            other = f"{name}_x"
            databases.append(other)
            _sql(admin_url, f"CREATE DATABASE {other} OWNER {owner}")
            return other

    yield Scratch()
    for database in databases:
        _sql(admin_url, f"DROP DATABASE IF EXISTS {database} WITH (FORCE)")
    _drop_cluster_objects(admin_url)


def alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CARVIS_")}
    env.update(CARVIS_MIGRATION_DATABASE_URL=url, PYTHON_DOTENV_DISABLED="1")
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args], cwd=BACKEND,
                            env=env, capture_output=True, text=True, timeout=120)
    assert PASSWORD not in result.stdout + result.stderr, "a credential reached migration output"
    return result


def ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stderr[-2000:]


def catalog(url: str) -> dict:
    """Roles, memberships, schemas, ACLs and comments relevant to B1, in comparable form."""
    roles = _sql(url, "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolcanlogin, "
                      "rolinherit, shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname LIKE 'carvis%' "
                      "ORDER BY 1", fetch=True)
    members = _sql(url, "SELECT r.rolname, m.rolname, g.rolname, a.admin_option, a.inherit_option, a.set_option "
                        "FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
                        "JOIN pg_roles g ON g.oid = a.grantor WHERE r.rolname LIKE 'carvis%' OR m.rolname LIKE 'carvis%' "
                        "ORDER BY 1, 2, 3", fetch=True)
    schemas = _sql(url, "SELECT nspname, pg_get_userbyid(nspowner), nspacl::text, obj_description(oid, 'pg_namespace') "
                        "FROM pg_namespace WHERE nspname IN ('carvis', 'carvis_migrations', 'public') ORDER BY 1",
                   fetch=True)
    tables = _sql(url, "SELECT n.nspname, c.relname, pg_get_userbyid(c.relowner), c.relacl::text FROM pg_class c "
                       "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('carvis', 'carvis_migrations', "
                       "'public') AND c.relkind IN ('r', 'v', 'S') ORDER BY 1, 2", fetch=True)
    return {"roles": roles, "members": members, "schemas": schemas, "tables": tables}


def _public(snapshot):
    return [row for row in snapshot["schemas"] if row[0] == "public"]


def _assert_roles_created(url: str) -> None:
    snapshot = catalog(url)
    by_name = {row[0]: row for row in snapshot["roles"]}
    assert set(by_name) == set(ROLES)
    for row in by_name.values():
        # no superuser, createdb, createrole, replication, bypassrls; NOLOGIN; marked
        assert row[1:7] == (False, False, False, False, False, False), row
        assert row[8] == MARKER
    schemas = {row[0]: row for row in snapshot["schemas"]}
    assert schemas["carvis"][1] == "carvis_owner"
    assert schemas["carvis"][3] == MARKER
    acl = schemas["carvis"][2]
    assert "carvis_app=U/carvis_owner" in acl and "carvis_worker=U/carvis_owner" in acl
    assert "=U/" not in acl.replace("carvis_app=U/", "").replace("carvis_worker=U/", "")  # no PUBLIC entry
    version = [row for row in snapshot["tables"] if row[:2] == ("carvis_migrations", "alembic_version")]
    assert version and "carvis_app=r/" in version[0][3] and "carvis_worker=r/" in version[0][3]


def _round_trip(scratch, url: str) -> None:
    before = catalog(scratch.db_admin)
    ok(alembic(url, "upgrade", "head"))
    _assert_roles_created(scratch.db_admin)
    first = catalog(scratch.db_admin)
    ok(alembic(url, "downgrade", "base"))
    after_down = catalog(scratch.db_admin)
    assert not after_down["roles"], "downgrade must drop the roles this revision created"
    assert [row[0] for row in after_down["schemas"]] == ["carvis_migrations", "public"]
    assert _public(after_down) == _public(before), "public schema ACL must never change"
    ok(alembic(url, "upgrade", "head"))
    assert catalog(scratch.db_admin) == first, "upgrade → downgrade → upgrade must give an identical catalog"
    assert _public(first) == _public(before)


def test_round_trip_as_superuser(scratch):
    _round_trip(scratch, scratch.db_admin)


def test_round_trip_as_non_superuser_createrole_database_owner(scratch):
    url = scratch.login("b1_migrator", "CREATEROLE")
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO b1_migrator")
    _round_trip(scratch, url)
    members = catalog(scratch.db_admin)["members"]
    # The migrator can assume carvis_owner (SET) without inheriting its rights.
    assert ("carvis_owner", "b1_migrator", "b1_migrator", False, False, True) in members


def test_login_without_createrole_fails_before_any_change(scratch):
    url = scratch.login("b1_plain")
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO b1_plain")
    result = alembic(url, "upgrade", "head")
    assert result.returncode != 0 and "needs CREATEROLE" in result.stderr
    snapshot = catalog(scratch.db_admin)
    assert not snapshot["roles"] and "carvis" not in [row[0] for row in snapshot["schemas"]]


def test_login_without_database_create_fails_with_named_privilege(scratch):
    url = scratch.login("b1_noowner", "CREATEROLE")
    result = alembic(url, "upgrade", "head")
    assert result.returncode != 0 and "CREATE on the database" in result.stderr
    assert not catalog(scratch.db_admin)["roles"]


def test_compatible_preexisting_role_is_adopted_and_survives_downgrade(scratch):
    _sql(scratch.admin, "CREATE ROLE carvis_app NOLOGIN")
    ok(alembic(scratch.db_admin, "upgrade", "head"))
    app = [row for row in catalog(scratch.db_admin)["roles"] if row[0] == "carvis_app"][0]
    assert app[6] is False and app[8] is None, "adopted role is not modified or marked"
    ok(alembic(scratch.db_admin, "downgrade", "base"))
    assert [row[0] for row in catalog(scratch.db_admin)["roles"]] == ["carvis_app"]


@pytest.mark.parametrize("setup,message", [
    (["CREATE ROLE carvis_app NOLOGIN BYPASSRLS"], "incompatible attributes: rolbypassrls"),
    (["CREATE ROLE carvis_worker NOLOGIN CREATEROLE"], "incompatible attributes: rolcreaterole"),
    (["CREATE ROLE carvis_app NOLOGIN SUPERUSER"], "incompatible attributes: rolsuper"),
    (["CREATE ROLE carvis_owner LOGIN"], "carvis_owner must be NOLOGIN"),
    (["CREATE ROLE carvis_app LOGIN"], "carvis_app must be NOLOGIN"),
    (["CREATE ROLE carvis_worker LOGIN PASSWORD 'x'"], "carvis_worker must be NOLOGIN"),
    (["CREATE ROLE carvis_app NOLOGIN", "GRANT pg_read_all_data TO carvis_app"], "member of another role"),
    (["CREATE ROLE carvis_owner NOLOGIN", "CREATE ROLE b1_other LOGIN", "GRANT carvis_owner TO b1_other"],
     "members other than"),
    (["CREATE ROLE carvis_app NOLOGIN", "CREATE ROLE b1_other LOGIN BYPASSRLS", "GRANT carvis_app TO b1_other"],
     "carvis_app has members"),
    (["CREATE ROLE carvis_worker NOLOGIN", "CREATE ROLE b1_other LOGIN", "GRANT carvis_worker TO b1_other"],
     "carvis_worker has members; no runtime login is approved yet"),
    (["CREATE ROLE carvis_app NOLOGIN", "CREATE ROLE carvis_owner NOLOGIN", "GRANT carvis_app TO carvis_owner"],
     "member of another role|has members"),
])
def test_incompatible_preexisting_role_fails_closed_without_modification(scratch, setup, message):
    _sql(scratch.admin, *setup)
    before = catalog(scratch.db_admin)
    result = alembic(scratch.db_admin, "upgrade", "head")
    assert result.returncode != 0
    import re

    assert re.search(message, result.stderr), result.stderr[-1500:]
    after = catalog(scratch.db_admin)
    assert after["roles"] == before["roles"] and after["members"] == before["members"]
    assert "carvis" not in [row[0] for row in after["schemas"]]


def test_non_superuser_needs_admin_option_on_preexisting_role(scratch):
    _sql(scratch.admin, "CREATE ROLE carvis_owner NOLOGIN")
    url = scratch.login("b1_migrator", "CREATEROLE")
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO b1_migrator")
    result = alembic(url, "upgrade", "head")
    assert result.returncode != 0 and "needs ADMIN OPTION on existing role carvis_owner" in result.stderr


def test_non_superuser_adopts_runtime_role_it_administers(scratch):
    """The implicit administrative grant a CREATEROLE login holds on a role it created is permitted."""
    url = scratch.login("b1_migrator", "CREATEROLE")
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO b1_migrator")
    _sql(url, "CREATE ROLE carvis_worker NOLOGIN")
    ok(alembic(url, "upgrade", "head"))
    ok(alembic(url, "downgrade", "base"))
    assert [row[0] for row in catalog(scratch.db_admin)["roles"]] == ["carvis_worker"]


def test_preexisting_owner_grant_by_migrator_fails_closed(scratch):
    url = scratch.login("b1_migrator", "CREATEROLE")
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO b1_migrator")
    _sql(url, "CREATE ROLE carvis_owner NOLOGIN", "GRANT carvis_owner TO b1_migrator WITH INHERIT FALSE, SET TRUE")
    result = alembic(url, "upgrade", "head")
    assert result.returncode != 0 and "members other than" in result.stderr


def test_preexisting_carvis_schema_is_refused(scratch):
    _sql(scratch.db_admin, "CREATE SCHEMA carvis")
    result = alembic(scratch.db_admin, "upgrade", "head")
    assert result.returncode != 0 and "already exists; refusing to adopt it" in result.stderr
    assert not catalog(scratch.db_admin)["roles"]


def test_metadata_schema_owned_by_someone_else_is_refused(scratch):
    url = scratch.login("b1_migrator", "CREATEROLE")
    _sql(scratch.admin, f"ALTER DATABASE {scratch.database} OWNER TO b1_migrator")
    _sql(scratch.db_admin, "CREATE SCHEMA carvis_migrations")
    result = alembic(url, "upgrade", "head")
    assert result.returncode != 0 and "not owned by the migration login" in result.stderr


def test_missing_migration_url_fails_without_fallback(scratch, monkeypatch):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CARVIS_")}
    env.update(CARVIS_DATABASE_URL=scratch.db_admin, PYTHON_DOTENV_DISABLED="1")
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
                            cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and "CARVIS_MIGRATION_DATABASE_URL" in result.stderr
    assert "carvis_migrations" not in [row[0] for row in catalog(scratch.db_admin)["schemas"]]


def _readiness(url: str) -> str:
    probe = ReadinessProbe("0002_roles", postgres_fetch(url), 3.0)
    return asyncio.run(probe.check()).reason


def test_readiness_as_runtime_member_without_elevation(scratch):
    runtime = scratch.login("b1_runtime")
    assert _readiness(runtime) == MIGRATIONS_PENDING  # nothing migrated yet
    ok(alembic(scratch.db_admin, "upgrade", "0001_baseline"))
    assert _readiness(scratch.db_admin) == MIGRATIONS_PENDING  # behind head
    ok(alembic(scratch.db_admin, "upgrade", "head"))
    assert _readiness(runtime) == DATABASE_UNREACHABLE  # not a member of carvis_app: permission denied
    _sql(scratch.admin, "GRANT carvis_app TO b1_runtime")
    assert _readiness(runtime) == READY
    ok(alembic(scratch.db_admin, "downgrade", "0001_baseline"))
    assert _readiness(scratch.db_admin) == MIGRATIONS_PENDING


def test_session_factory_runs_one_unit_of_work(scratch):
    from sqlalchemy import text

    from db.engine import create_app_engine, create_session_factory
    from settings import normalize_database_url

    _, url = normalize_database_url(scratch.db_admin)
    engine = create_app_engine(url)
    try:
        with create_session_factory(engine)() as session:
            assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()


# --- Readiness address fallback against real PostgreSQL (round-2 review) -------------------------

@pytest.fixture
def fake_dns(monkeypatch):
    """Resolve ``db.fallback.test`` to a chosen address list; other names resolve normally."""
    import socket as socket_module

    real = socket_module.getaddrinfo
    answers: list[str] = []

    def fake(host, port, *args, **kwargs):
        if host == "db.fallback.test":
            out = []
            for address in answers:
                family = socket_module.AF_INET6 if ":" in address else socket_module.AF_INET
                sockaddr = (address, int(port), 0, 0) if family == socket_module.AF_INET6 else (address, int(port))
                out.append((family, socket_module.SOCK_STREAM, socket_module.IPPROTO_TCP, "", sockaddr))
            return out
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket_module, "getaddrinfo", fake)
    return answers


def _named_url(admin: str, database: str | None = None) -> str:
    from sqlalchemy.engine import make_url

    url = make_url(admin)
    url = url.set(host="db.fallback.test", query={**url.query, "sslmode": "disable"})
    if database is not None:
        url = url.set(database=database)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _timed_readiness(url: str) -> tuple[str, float, int]:
    import time

    from db.readiness import BoundedResolver

    resolver = BoundedResolver()
    probe = ReadinessProbe("0002_roles", postgres_fetch(url, resolver, 2.0), 2.0, resolver=resolver)

    async def scenario():
        started = time.monotonic()
        result = await probe.check()
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        return result.reason, time.monotonic() - started, len(pending)

    try:
        return asyncio.run(scenario())
    finally:
        resolver.shutdown()


@pytest.mark.parametrize("first", ["192.0.2.1", "2001:db8::1", "::1"])
def test_unreachable_first_address_falls_back_within_one_deadline(scratch, fake_dns, first):
    """TEST-NET (silently dropped or unroutable) and IPv6 first addresses, then the reachable IPv4 one."""
    from sqlalchemy.engine import make_url

    host = make_url(scratch.admin).host
    fake_dns[:] = [first, host]
    ok(alembic(scratch.db_admin, "upgrade", "head"))
    reason, elapsed, pending = _timed_readiness(_named_url(scratch.admin, scratch.database))
    assert reason == READY, reason
    assert elapsed < 2.5 and pending == 0


def test_mixed_addresses_report_pending_until_migrated(scratch, fake_dns):
    from sqlalchemy.engine import make_url

    fake_dns[:] = ["2001:db8::2", make_url(scratch.admin).host, "192.0.2.2"]
    assert _timed_readiness(_named_url(scratch.admin, scratch.database))[0] == MIGRATIONS_PENDING


def test_all_addresses_unreachable_is_bounded(scratch, fake_dns):
    fake_dns[:] = ["192.0.2.3", "2001:db8::3", "192.0.2.4"]
    reason, elapsed, pending = _timed_readiness(_named_url(scratch.admin, scratch.database))
    assert reason == DATABASE_UNREACHABLE
    assert elapsed < 2.5 and pending == 0
