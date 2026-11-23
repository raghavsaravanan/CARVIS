"""Explicit-connection rules shared by settings and readiness (M2 B2a; B1 deferred N2 and N3).

CARVIS connections must be fully described by the configured URL plus libpq's host/port variables:

- **Service files are refused (N3).** A ``service``/``servicefile`` parameter or a ``PGSERVICE`` /
  ``PGSERVICEFILE`` variable would let libpq read hosts, ports and options from a file that the
  bounded resolver never sees, so libpq would resolve names itself, outside the probe's deadline.
- **Host and port counts follow libpq's rule (N2).** The effective hosts come from the ``host``
  parameter, else ``PGHOST``; the effective ports from ``port``, else ``PGPORT``. libpq accepts one
  port for every host or exactly one port per host and rejects anything else; CARVIS rejects the same
  configurations instead of silently using the first port.

Errors name the rule only, never a value.
"""

from __future__ import annotations

import os
from typing import Mapping

SERVICE_PARAMETERS = ("service", "servicefile")
SERVICE_VARIABLES = ("PGSERVICE", "PGSERVICEFILE")
DEFAULT_PORT = "5432"


class ConnectionConfigError(ValueError):
    """The connection settings are not explicit enough for CARVIS. Names the rule, never values."""


def reject_service_files(params: Mapping[str, object], environ: Mapping[str, str] | None = None) -> None:
    environ = os.environ if environ is None else environ
    if any(str(params.get(name) or "").strip() for name in SERVICE_PARAMETERS):
        raise ConnectionConfigError("libpq service files are not supported; configure hosts in the URL.")
    if any((environ.get(name) or "").strip() for name in SERVICE_VARIABLES):
        raise ConnectionConfigError("PGSERVICE and PGSERVICEFILE are not supported; configure hosts in the URL.")


def host_port_entries(params: Mapping[str, object], environ: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """``(host, port)`` per effective host, in configured order, applying libpq's count rule.

    An empty host means libpq's default (a Unix socket); an empty port means the default port.
    """
    environ = os.environ if environ is None else environ
    hosts_value = str(params.get("host") or environ.get("PGHOST") or "")
    ports_value = str(params.get("port") or environ.get("PGPORT") or "")
    hosts = hosts_value.split(",")
    ports = ports_value.split(",")
    if len(ports) != 1 and len(ports) != len(hosts):
        raise ConnectionConfigError("The number of ports must be one or match the number of hosts.")
    return [(host, (ports[index] if len(ports) > 1 else ports[0]) or DEFAULT_PORT)
            for index, host in enumerate(hosts)]


def validate_conninfo(conninfo: str, environ: Mapping[str, str] | None = None) -> None:
    """Apply both rules to a libpq connection string. Never echoes the string."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        params = conninfo_to_dict(conninfo)
    except Exception:  # noqa: BLE001 - a parse error can quote the string; its text is discarded
        raise ConnectionConfigError("The connection string cannot be parsed.") from None
    reject_service_files(params, environ)
    host_port_entries(params, environ)
