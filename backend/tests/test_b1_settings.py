"""M2 B1: typed settings keep the existing fail-closed guards and add the PostgreSQL URL safely.

Nothing here contacts a database or provider.
"""
from __future__ import annotations

import traceback

import pytest

from deployment_config import DeploymentConfigurationError
from settings import (DATABASE_URL_ENV, PSYCOPG_DRIVER, DatabaseConfigurationError, DatabaseUrl, load_settings,
                      normalize_database_url)
from webhook_auth import WebhookConfigurationError

SECRET_PASSWORD = "Sup3rSecretPw"


@pytest.fixture
def env(monkeypatch):
    """A complete non-local configuration; tests remove or change one thing."""
    for name in ("CARVIS_ENV", "RENDER", DATABASE_URL_ENV, "SPACETIMEDB_URI", "SPACETIMEDB_TOKEN",
                 "SPACETIMEDB_DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CARVIS_ENV", "production")
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("CARVIS_DEFAULT_SHOP_ID", "shop_test")
    monkeypatch.setenv("CARVIS_QDRANT_COLLECTION", "carvis_specs_v2")
    return monkeypatch


def test_unset_environment_is_production_and_fails_closed_without_secret(env):
    env.delenv("CARVIS_ENV")
    env.delenv("VAPI_WEBHOOK_SECRET")
    with pytest.raises(WebhookConfigurationError):
        load_settings()


def test_existing_guard_order_is_preserved(env):
    # Both the secret and the shop are missing: the webhook guard (first) must be the one that fires.
    env.delenv("VAPI_WEBHOOK_SECRET")
    env.delenv("CARVIS_DEFAULT_SHOP_ID")
    with pytest.raises(WebhookConfigurationError):
        load_settings()


def test_explicit_configuration_guard_still_applies(env):
    env.delenv("CARVIS_QDRANT_COLLECTION")
    with pytest.raises(DeploymentConfigurationError, match="CARVIS_QDRANT_COLLECTION"):
        load_settings()


def test_local_reports_defaults_and_allows_missing_values(env):
    env.setenv("CARVIS_ENV", "local")
    env.delenv("VAPI_WEBHOOK_SECRET")
    env.delenv("CARVIS_DEFAULT_SHOP_ID")
    loaded = load_settings()
    assert loaded.environment == "local"
    assert "CARVIS_DEFAULT_SHOP_ID" in loaded.local_defaults


def test_database_url_is_optional_but_never_probed_when_missing(env):
    loaded = load_settings()
    assert loaded.database_status == "unconfigured"
    assert loaded.database_url is None
    assert not loaded.database_ready_to_probe


@pytest.mark.parametrize("raw", [
    "postgresql://u:p@db.example/carvis",
    "postgres://u:p@db.example/carvis",
    "postgresql+psycopg://u:p@db.example/carvis",
    "postgresql://u:p@db.example:6543/carvis?sslmode=require&application_name=carvis",
])
def test_supported_urls_normalize_to_psycopg3(raw):
    status, url = normalize_database_url(raw)
    assert status == "configured"
    revealed = url.reveal()
    assert revealed.startswith(PSYCOPG_DRIVER + "://")
    # Credentials, host, database and query parameters pass through; nothing provider-specific is added.
    from sqlalchemy.engine import make_url

    original, normalized = make_url(raw), make_url(revealed)
    assert (normalized.username, normalized.password, normalized.host, normalized.port, normalized.database,
            dict(normalized.query)) == (original.username, original.password, original.host, original.port,
                                        original.database, dict(original.query))


@pytest.mark.parametrize("raw", [
    "mysql://u:p@db.example/carvis",
    "postgresql+psycopg2://u:p@db.example/carvis",
    "postgresql+asyncpg://u:p@db.example/carvis",
    "sqlite:///carvis.db",
    "not a url",
    "postgresql://",
    f"postgresql://user@host:{SECRET_PASSWORD}/db",
    f"postgresql://user:x@h:{SECRET_PASSWORD}@host/db",
])
def test_unsupported_urls_are_invalid(raw):
    assert normalize_database_url(raw) == ("invalid", None)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_urls_are_unconfigured(raw):
    assert normalize_database_url(raw) == ("unconfigured", None)


def test_invalid_url_refuses_boot_outside_local_without_leaking(env):
    env.setenv(DATABASE_URL_ENV, f"postgresql://user@host:{SECRET_PASSWORD}/db")
    with pytest.raises(DatabaseConfigurationError) as caught:
        load_settings()
    error = caught.value
    rendered = "".join(traceback.format_exception(error))
    assert SECRET_PASSWORD not in rendered
    assert error.__cause__ is None and error.__context__ is None
    assert DATABASE_URL_ENV in str(error)


def test_invalid_url_in_local_boots_but_is_marked_invalid(env):
    env.setenv("CARVIS_ENV", "local")
    env.setenv(DATABASE_URL_ENV, "mysql://u:p@db.example/carvis")
    loaded = load_settings()
    assert loaded.database_status == "invalid"
    assert not loaded.database_ready_to_probe


def test_url_value_is_never_rendered(env):
    env.setenv(DATABASE_URL_ENV, f"postgresql://carvis:{SECRET_PASSWORD}@db.example/carvis")
    loaded = load_settings()
    assert loaded.database_ready_to_probe
    for rendered in (repr(loaded), str(loaded), repr(loaded.database_url), str(loaded.database_url),
                     f"{loaded.database_url}"):
        assert SECRET_PASSWORD not in rendered
    assert SECRET_PASSWORD in loaded.database_url.reveal()


def test_database_url_equality_does_not_render():
    assert DatabaseUrl("a") == DatabaseUrl("a") and DatabaseUrl("a") != DatabaseUrl("b")
