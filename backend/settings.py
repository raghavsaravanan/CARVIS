"""Typed startup settings for the Carvis API (M2 Track B1).

:func:`load_settings` is the single startup entry point for configuration. It runs the existing
fail-closed guards unchanged and in their original order (the Vapi webhook secret and environment
from :mod:`webhook_auth`, then the explicit shop, collection and SpacetimeDB names from
:mod:`deployment_config`), then adds the PostgreSQL settings. It reads ``os.environ`` only, the same
source those guards read, so settings and guards can never see different environments.

``CARVIS_DATABASE_URL`` is optional in B1 by owner decision (transitional): requiring it outside
local would refuse boot on the current deployment. A missing or invalid URL never produces
readiness (``/readyz`` answers 503). Outside local an invalid URL refuses boot. Supported schemes
(``postgresql``, ``postgres``, ``postgresql+psycopg``) are normalized to the psycopg 3 driver;
nothing about hosts, ports, TLS, poolers or issuers is assumed, and query parameters pass through.

No setting value is ever logged or placed in an exception: errors name the setting only, and the
URL is held in :class:`DatabaseUrl`, whose ``repr`` and ``str`` are redacted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from deployment_config import require_explicit_configuration_at_boot
from webhook_auth import LOCAL, require_webhook_secret_at_boot

DATABASE_URL_ENV = "CARVIS_DATABASE_URL"
MIGRATION_DATABASE_URL_ENV = "CARVIS_MIGRATION_DATABASE_URL"
PSYCOPG_DRIVER = "postgresql+psycopg"
SUPPORTED_SCHEMES = frozenset({"postgresql", "postgres", PSYCOPG_DRIVER})
READINESS_TIMEOUT_SECONDS = 2.0
REDACTED = "[redacted]"

DatabaseStatus = Literal["configured", "unconfigured", "invalid"]


class DatabaseConfigurationError(RuntimeError):
    """Raised at startup when the database URL is unusable outside local. Names the setting only."""


class DatabaseUrl:
    """A database URL that never renders its value; use :meth:`reveal` to pass it to a driver."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"DatabaseUrl({REDACTED})"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DatabaseUrl) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


def _parse(raw: str) -> str | None:
    """The URL normalized to psycopg 3, or ``None``. Never raises: a parse error can quote the URL."""
    try:
        from sqlalchemy.engine import make_url

        url = make_url(raw)
        if url.drivername not in SUPPORTED_SCHEMES or not url.database and not url.host and not url.query:
            return None
        return url.set(drivername=PSYCOPG_DRIVER).render_as_string(hide_password=False)
    except Exception:  # noqa: BLE001 - any failure means "not a supported URL"; its text is discarded
        return None


def normalize_database_url(raw: str | None) -> tuple[DatabaseStatus, DatabaseUrl | None]:
    """Classify and normalize a database URL setting."""
    value = (raw or "").strip()
    if not value:
        return "unconfigured", None
    normalized = _parse(value)
    if normalized is None:
        return "invalid", None
    return "configured", DatabaseUrl(normalized)


@dataclass(frozen=True)
class Settings:
    environment: str
    database_status: DatabaseStatus
    database_url: DatabaseUrl | None
    readiness_timeout_seconds: float = READINESS_TIMEOUT_SECONDS
    local_defaults: tuple[str, ...] = ()

    @property
    def database_ready_to_probe(self) -> bool:
        return self.database_status == "configured" and self.database_url is not None


def load_settings() -> Settings:
    """Validate startup configuration; refuse to boot when a fail-closed rule is violated."""
    environment = require_webhook_secret_at_boot()
    local_defaults = tuple(require_explicit_configuration_at_boot(environment))
    status, url = normalize_database_url(os.getenv(DATABASE_URL_ENV))
    if status == "invalid" and environment != LOCAL:
        raise DatabaseConfigurationError(f"{DATABASE_URL_ENV} is not a supported PostgreSQL URL.")
    return Settings(environment=environment, database_status=status, database_url=url,
                    local_defaults=local_defaults)
