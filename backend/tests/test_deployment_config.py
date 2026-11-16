"""M2 Track A4: no silent shop_demo, george_specs or hackutd defaults outside local.

Outside CARVIS_ENV=local the API refuses to boot unless CARVIS_DEFAULT_SHOP_ID and
CARVIS_QDRANT_COLLECTION are explicit, and SPACETIMEDB_DB_NAME is explicit whenever SpacetimeDB is
configured. The check runs before models or Qdrant load. Locally the old values still apply, and
explicit values are used exactly as before everywhere.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import deployment_config
import main
from deployment_config import (COLLECTION_ENV, DEFAULT_SHOP_ENV, SPACETIMEDB_DB_ENV, DeploymentConfigurationError,
                               default_shop_id, missing_explicit_settings, spacetimedb_db_name)

BACKEND = Path(__file__).resolve().parents[1]
REQUIRED = {DEFAULT_SHOP_ENV: "shop_pilot", COLLECTION_ENV: "carvis_specs_active"}
ALL_NAMES = (DEFAULT_SHOP_ENV, COLLECTION_ENV, SPACETIMEDB_DB_ENV, "SPACETIMEDB_URI", "SPACETIMEDB_TOKEN")


class FakeQdrant:
    def __init__(self, *args, **kwargs):
        pass

    def collection_exists(self, name):
        return True

    def close(self):
        pass


@pytest.fixture
def boot(monkeypatch):
    """Run the real lifespan with the embedding model and Qdrant faked; never touches a provider."""
    for name in ("CARVIS_ENV", "RENDER", *ALL_NAMES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "webhook-secret-for-boot")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.invalid")
    monkeypatch.setenv("QDRANT_API_KEY", "test-only")
    embedder = MagicMock(name="TextEmbedding")
    monkeypatch.setattr(main, "TextEmbedding", embedder)
    monkeypatch.setattr(main, "QdrantClient", FakeQdrant)
    monkeypatch.setattr(main, "_VISION_CLIENT", None)
    saved_state = dict(main.app.state._state)
    level = main.logger.level

    async def start():
        async with main.lifespan(main.app):
            return True

    def boot_once():
        return asyncio.run(start())

    boot_once.embedder = embedder
    yield boot_once
    main.app.state._state.clear()
    main.app.state._state.update(saved_state)
    main.logger.setLevel(level)


def set_env(monkeypatch, values):
    for name, value in values.items():
        monkeypatch.setenv(name, value)


# --- Boot refusal outside local ----------------------------------------------------------------


@pytest.mark.parametrize("environment", [None, "production", "staging"])
def test_boot_refuses_without_explicit_shop_and_collection(boot, monkeypatch, environment):
    if environment:
        monkeypatch.setenv("CARVIS_ENV", environment)
    with pytest.raises(DeploymentConfigurationError) as exc:
        boot()
    assert DEFAULT_SHOP_ENV in str(exc.value) and COLLECTION_ENV in str(exc.value)
    assert not boot.embedder.called, "the check must run before models or Qdrant load"


@pytest.mark.parametrize("environment", [None, "production", "staging"])
@pytest.mark.parametrize("missing", [DEFAULT_SHOP_ENV, COLLECTION_ENV])
@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_each_required_setting_is_enforced(boot, monkeypatch, environment, missing, value):
    if environment:
        monkeypatch.setenv("CARVIS_ENV", environment)
    set_env(monkeypatch, {k: v for k, v in REQUIRED.items() if k != missing})
    if value is not None:
        monkeypatch.setenv(missing, value)
    with pytest.raises(DeploymentConfigurationError, match=missing) as exc:
        boot()
    other = next(name for name in REQUIRED if name != missing)
    assert other not in str(exc.value), "only the missing setting is named"
    assert not boot.embedder.called


ACTIVE_TELEMETRY = {"SPACETIMEDB_URI": "https://stdb.invalid", "SPACETIMEDB_TOKEN": "stdb-token"}


@pytest.mark.parametrize("spacetime", [ACTIVE_TELEMETRY, {**ACTIVE_TELEMETRY, SPACETIMEDB_DB_ENV: "  "}],
                         ids=["uri-and-token", "blank-db-name"])
def test_active_spacetimedb_requires_an_explicit_database(boot, monkeypatch, spacetime):
    monkeypatch.setenv("CARVIS_ENV", "production")
    set_env(monkeypatch, {**REQUIRED, **spacetime})
    with pytest.raises(DeploymentConfigurationError, match=SPACETIMEDB_DB_ENV):
        boot()
    assert not boot.embedder.called


@pytest.mark.parametrize("environment", [None, "production", "staging"])
def test_boot_with_explicit_settings_succeeds(boot, monkeypatch, environment):
    if environment:
        monkeypatch.setenv("CARVIS_ENV", environment)
    set_env(monkeypatch, REQUIRED)
    assert boot()
    assert boot.embedder.called


@pytest.mark.parametrize("partial", [{"SPACETIMEDB_URI": "https://stdb.invalid"}, {"SPACETIMEDB_TOKEN": "t"}],
                         ids=["uri-only", "token-only"])
def test_partial_spacetimedb_settings_leave_telemetry_off_and_boot(boot, monkeypatch, partial):
    """Telemetry needs both; with one missing it never runs, so no database name can be used."""
    monkeypatch.setenv("CARVIS_ENV", "production")
    set_env(monkeypatch, {**REQUIRED, **partial})
    assert boot()


def test_spacetimedb_stays_optional(boot, monkeypatch):
    """With no SpacetimeDB settings, telemetry is off and its database name is not required."""
    monkeypatch.setenv("CARVIS_ENV", "production")
    set_env(monkeypatch, REQUIRED)
    assert missing_explicit_settings() == []
    assert boot()


def test_fully_configured_spacetimedb_boots(boot, monkeypatch):
    monkeypatch.setenv("CARVIS_ENV", "staging")
    set_env(monkeypatch, {**REQUIRED, "SPACETIMEDB_URI": "https://stdb.invalid", "SPACETIMEDB_TOKEN": "t",
                          SPACETIMEDB_DB_ENV: "carvis_staging"})
    assert boot()


def test_render_requires_explicit_settings(boot, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(DeploymentConfigurationError):
        boot()
    set_env(monkeypatch, REQUIRED)
    assert boot()


def test_webhook_secret_is_still_checked_first(boot, monkeypatch):
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET")
    from webhook_auth import WebhookConfigurationError
    with pytest.raises(WebhookConfigurationError):
        boot()


def test_refusal_names_settings_but_never_values(boot, monkeypatch, caplog):
    monkeypatch.setenv("CARVIS_ENV", "production")
    secretish = "https://user:hunter2-stdb-credential@stdb.invalid"
    set_env(monkeypatch, {COLLECTION_ENV: "carvis_specs_active", "SPACETIMEDB_URI": secretish,
                          "SPACETIMEDB_TOKEN": "stdb-token-value-123"})
    with caplog.at_level("DEBUG"), pytest.raises(DeploymentConfigurationError) as exc:
        boot()
    for value in (secretish, "stdb-token-value-123", "carvis_specs_active", "webhook-secret-for-boot"):
        assert value not in str(exc.value)
        assert value not in caplog.text


# --- Local keeps its defaults ------------------------------------------------------------------


def test_local_boots_with_the_previous_defaults(boot, monkeypatch, caplog):
    monkeypatch.setenv("CARVIS_ENV", "local")
    with caplog.at_level("INFO", logger="carvis.main"):
        assert boot()
    for name in (DEFAULT_SHOP_ENV, COLLECTION_ENV):
        assert f"{name} is not set; using its local default" in caplog.text
    assert default_shop_id() == "shop_demo"
    assert spacetimedb_db_name() == "hackutd"
    assert deployment_config.LOCAL_COLLECTION == "george_specs"


def test_local_boot_without_the_webhook_secret_still_allowed(boot, monkeypatch):
    monkeypatch.setenv("CARVIS_ENV", "local")
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET")
    assert boot()


# --- Explicit values are used ------------------------------------------------------------------


def test_explicit_values_are_normalized_like_request_shop_ids(monkeypatch):
    monkeypatch.setenv(DEFAULT_SHOP_ENV, "  Shop_Pilot \n")
    monkeypatch.setenv(SPACETIMEDB_DB_ENV, " carvis_staging ")
    assert default_shop_id() == "shop_pilot"
    assert spacetimedb_db_name() == "carvis_staging"


def test_configured_values_reach_the_api_module():
    """main captures these at import, so check a fresh interpreter rather than this one."""
    env = {k: v for k, v in os.environ.items() if k not in ALL_NAMES}
    env.update({DEFAULT_SHOP_ENV: "Shop_Pilot", COLLECTION_ENV: "carvis_specs_active",
                SPACETIMEDB_DB_ENV: "carvis_staging", "CARVIS_ENV": "production"})
    script = ("import main, inspect; "
              "print(main.DEFAULT_SHOP_ID, main.COLLECTION_NAME, main.SPACETIMEDB_DB_NAME, "
              "inspect.signature(main.search_top_chunk).parameters['shop_id'].default, "
              "main.VehicleBody(year='2022', make='a', model='b').shop_id)")
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["shop_pilot", "carvis_specs_active", "carvis_staging", "shop_pilot",
                                     "shop_pilot"]


@pytest.mark.skipif((BACKEND / ".env").exists(), reason="a local backend/.env would supply these settings")
def test_unconfigured_import_keeps_local_defaults():
    env = {k: v for k, v in os.environ.items() if k not in ALL_NAMES}
    script = "import main; print(main.DEFAULT_SHOP_ID, main.COLLECTION_NAME, main.SPACETIMEDB_DB_NAME)"
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["shop_demo", "george_specs", "hackutd"]


@pytest.mark.parametrize("raw, expected", [("  carvis_specs_active \n", "carvis_specs_active"), ("   ", "george_specs")],
                         ids=["padded", "blank"])
def test_collection_is_read_the_way_the_boot_check_reads_it(raw, expected):
    """A value that passes (or fails) the check is exactly what the API then uses."""
    env = {k: v for k, v in os.environ.items() if k not in ALL_NAMES}
    env[COLLECTION_ENV] = raw
    result = subprocess.run([sys.executable, "-c", "import main; print(repr(main.COLLECTION_NAME))"], cwd=BACKEND,
                            env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == repr(expected)


def test_suite_is_pinned_to_the_local_default_shop():
    """conftest pins this before main is imported, whatever the developer's environment says."""
    assert main.DEFAULT_SHOP_ID == "shop_demo"
