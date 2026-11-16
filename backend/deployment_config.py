"""Explicit tenant, collection and telemetry settings outside local (M2 Track A4).

The API used to fall back silently to ``shop_demo`` (the shop for every request that omits
``shop_id``, which the iOS app always does), the ``george_specs`` collection, and the ``hackutd``
SpacetimeDB database. Those fallbacks now apply only with ``CARVIS_ENV=local``. Every other
environment refuses to boot unless the settings are explicit, so a deployment cannot quietly
serve the demo shop, read the legacy collection, or write telemetry to the hackathon database.

Values are resolved at import with the local fallbacks so that tests and CLIs can import the
modules; :func:`require_explicit_configuration_at_boot` runs before the API serves anything.
"""

from __future__ import annotations

import os

from qdrant_v2 import LEGACY_COLLECTION
from webhook_auth import ENVIRONMENT_ENV, LOCAL

DEFAULT_SHOP_ENV = "CARVIS_DEFAULT_SHOP_ID"
COLLECTION_ENV = "CARVIS_QDRANT_COLLECTION"
SPACETIMEDB_DB_ENV = "SPACETIMEDB_DB_NAME"
# Telemetry runs only when both are set (main._spacetime_call_reducer), so only then does the
# database name stop being irrelevant.
SPACETIMEDB_SETTINGS = ("SPACETIMEDB_URI", "SPACETIMEDB_TOKEN")

LOCAL_DEFAULT_SHOP_ID = "shop_demo"
LOCAL_COLLECTION = LEGACY_COLLECTION
LOCAL_SPACETIMEDB_DB_NAME = "hackutd"


class DeploymentConfigurationError(RuntimeError):
    """Raised at startup when a required explicit setting is missing outside local."""


def _setting(name: str) -> str:
    return (os.getenv(name) or "").strip()


def default_shop_id() -> str:
    """Shop for requests that omit ``shop_id``: the explicit setting, else the local default."""
    return (_setting(DEFAULT_SHOP_ENV) or LOCAL_DEFAULT_SHOP_ID).lower()


def spacetimedb_db_name() -> str:
    """SpacetimeDB database name: the explicit setting, else the local default."""
    return _setting(SPACETIMEDB_DB_ENV) or LOCAL_SPACETIMEDB_DB_NAME


def missing_explicit_settings() -> list[str]:
    """Names of settings that would silently fall back to a local default."""
    missing = [name for name in (DEFAULT_SHOP_ENV, COLLECTION_ENV) if not _setting(name)]
    # SpacetimeDB telemetry is optional; its database name matters only once it would run.
    if all(_setting(name) for name in SPACETIMEDB_SETTINGS) and not _setting(SPACETIMEDB_DB_ENV):
        missing.append(SPACETIMEDB_DB_ENV)
    return missing


def require_explicit_configuration_at_boot(environment: str) -> list[str]:
    """Refuse to start outside local while a local default would apply.

    Returns the settings that fall back to local defaults (only ever non-empty for local). Error
    messages name settings, never their values.
    """
    missing = missing_explicit_settings()
    if missing and environment != LOCAL:
        raise DeploymentConfigurationError(
            f"{', '.join(missing)} must be set explicitly when {ENVIRONMENT_ENV}={environment}. "
            f"The local defaults apply only with {ENVIRONMENT_ENV}=local."
        )
    return missing
