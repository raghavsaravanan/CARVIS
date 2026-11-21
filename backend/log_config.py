"""Structured logging scaffold for the Carvis API (M2 Track A6).

Logs are one JSON object per line (``CARVIS_LOG_FORMAT=text`` keeps the human-readable format for
local work). Structured fields go through :func:`log_event`, which is an allowlist, not a filter:

- Only field names in :data:`FIELD_POLICY` are logged; any other name is dropped and listed in
  ``dropped_fields``.
- Each permitted field has a rule. Measurements are numbers or booleans. Server-generated IDs and
  codes must match an exact shape (a session prefix is 8 hex digits, a camera request ID 32).
  Closed vocabularies (component, operation, spec type, tool name, internal reason, vehicle field)
  accept only values registered with :func:`register_values`. A value that fails becomes
  ``"[redacted]"`` and is listed in ``redacted_fields``.
- Caller-supplied identifiers (Vapi call IDs, tool-call IDs, a legacy request's ``shop_id``) are
  never logged as given: they become a fingerprint, ``fp:`` plus 12 hex digits of an HMAC-SHA-256
  of the field name and value, keyed with a random per-process salt. A fingerprint correlates lines
  for one field within one process and cannot be reversed. Someone who can only read the logs cannot
  confirm a guessed value; someone who can also send requests can, by sending the guess and
  comparing, so fingerprints protect content, not secrets. A ``shop_id`` registered as known (the
  configured default shop) is logged as is.

So spoken questions, transcripts, answers, model output, phone-supplied reasons and caller-chosen
identifiers cannot reach a log through :func:`log_event`. Residual limits: plain ``logger.*`` calls
bypass the policy (request paths use :func:`log_event`, or fixed messages with type names and
counts), and loggers Carvis does not configure (uvicorn, httpx, openai) are outside it. Request IDs,
call IDs and metrics arrive with Track B1 (``docs/architecture/09-deployment-operations.md``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

LOG_FORMAT_ENV = "CARVIS_LOG_FORMAT"
TEXT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
REDACTED = "[redacted]"
FINGERPRINT_PREFIX = "fp:"
MAX_LIST_ITEMS = 16

_CODE = re.compile(r"[a-z][a-z0-9_]{0,47}")
_TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_SETTING = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SESSION_PREFIX = re.compile(r"[0-9a-f]{8}")
_REQUEST_ID = re.compile(r"[0-9a-f]{32}")
_VEHICLE_CORRECTED = "vehicle corrected: "
_REGISTERED: dict[str, frozenset[str]] = {}
_SALT = secrets.token_bytes(32)

Rule = Callable[[str, Any], Any]
"""Returns the value to log, or ``REDACTED``."""


def fingerprint(value: str, field: str = "") -> str:
    """A salted, per-process fingerprint of a caller-supplied identifier, separate per field."""
    message = field.encode() + b"\0" + value.encode("utf-8", "surrogateescape")
    digest = hmac.new(_SALT, message, hashlib.sha256).hexdigest()
    return FINGERPRINT_PREFIX + digest[:12]


def _check(predicate: Callable[[Any], bool]) -> Rule:
    return lambda _name, value: value if value is None or predicate(value) else REDACTED


def _matching(pattern: re.Pattern[str]) -> Rule:
    return _check(lambda value: isinstance(value, str) and bool(pattern.fullmatch(value)))


def _known(name: str, value: Any) -> bool:
    return isinstance(value, str) and value in _REGISTERED.get(name, frozenset())


def _registered(name: str, value: Any) -> Any:
    return value if value is None or _known(name, value) else REDACTED


def _reason(name: str, value: Any) -> Any:
    """A registered reason, or ``vehicle corrected: <known vehicle fields>``."""
    if value is None or _known(name, value):
        return value
    if isinstance(value, str) and value.startswith(_VEHICLE_CORRECTED):
        fields = value[len(_VEHICLE_CORRECTED):].split(", ")
        if fields and all(_known("vehicle_field", field) for field in fields):
            return value
    return REDACTED


def _fingerprinted(name: str, value: Any) -> Any:
    """Caller-supplied identifier: logged only as a fingerprint, unless registered as known."""
    if value is None or _known(name, value):
        return value
    return fingerprint(value, name) if isinstance(value, str) else REDACTED


def _list_of(item: Rule) -> Rule:
    def apply(name: str, value: Any) -> Any:
        if not isinstance(value, (list, tuple)) or len(value) > MAX_LIST_ITEMS:
            return REDACTED
        items = [item(name, element) for element in value]
        return REDACTED if REDACTED in items else items
    return apply


MEASURE = _check(lambda value: isinstance(value, (bool, int, float)))
CODE = _matching(_CODE)
TYPE_NAME = _matching(_TYPE_NAME)
REGISTERED = _registered
FINGERPRINTED = _fingerprinted

FIELD_POLICY: dict[str, Rule] = {
    # Measurements, flags and counts.
    **dict.fromkeys(("bytes", "confidence", "elapsed_ms", "generation", "has_opening_question", "has_query",
                     "has_vehicle", "makes", "min_score", "models", "page", "payload_keys", "query_chars",
                     "score", "tool_calls", "triples", "years"), MEASURE),
    # Server-generated identifiers and names, by exact shape.
    "session": _matching(_SESSION_PREFIX),
    "request_id": _matching(_REQUEST_ID),
    "setting": _matching(_SETTING),
    # Server-defined codes and exception type names (never exception messages).
    **dict.fromkeys(("code", "outcome", "pass_name", "stage"), CODE),
    "error": TYPE_NAME,
    # Closed vocabularies registered by the modules that own them.
    **dict.fromkeys(("component", "operation", "spec_type", "tool"), REGISTERED),
    "reason": _reason,
    "changed": _list_of(lambda _name, value: _registered("vehicle_field", value)),
    # Caller-supplied identifiers: fingerprints only.
    **dict.fromkeys(("shop_id", "tool_call_id", "vapi_call_id"), FINGERPRINTED),
}
"""The only loggable field names, each with the rule its value must pass."""

_VOCABULARY_FIELDS = frozenset({"component", "operation", "spec_type", "tool", "reason", "vehicle_field",
                                "shop_id"})


def register_values(field: str, values: Iterable[str]) -> None:
    """Allow these exact values for a vocabulary field, such as the known component codes, or the
    configured shop (logged as is rather than fingerprinted)."""
    if field not in _VOCABULARY_FIELDS:
        raise ValueError(f"{field} is not a registered-vocabulary field")
    _REGISTERED[field] = _REGISTERED.get(field, frozenset()) | frozenset(values)


def safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Apply :data:`FIELD_POLICY`: keep permitted values; drop, redact or fingerprint everything else."""
    safe: dict[str, Any] = {}
    dropped, redacted = [], []
    for name, value in fields.items():
        rule = FIELD_POLICY.get(name)
        if rule is None:
            dropped.append(name)
            continue
        logged = rule(name, value)
        safe[name] = logged
        if logged == REDACTED:
            redacted.append(name)
    if dropped:
        safe["dropped_fields"] = sorted(dropped)
    if redacted:
        safe["redacted_fields"] = sorted(redacted)
    return safe


_FIELDS_ATTR = "carvis_fields"


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Log the fixed message ``event`` with fields filtered by :data:`FIELD_POLICY`.

    ``event`` must be a constant written in code, never built from request data.
    """
    logger.log(level, event, extra={_FIELDS_ATTR: safe_fields(fields)})


class JsonFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, message, structured fields, exception."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, _FIELDS_ATTR, None)
        if fields:
            entry["fields"] = fields
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """The previous human-readable format, with structured fields appended."""

    def __init__(self) -> None:
        super().__init__(TEXT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = getattr(record, _FIELDS_ATTR, None)
        if fields:
            line += " " + " ".join(f"{key}={value!r}" for key, value in fields.items())
        return line


def formatter_from_environment() -> logging.Formatter:
    chosen = (os.getenv(LOG_FORMAT_ENV) or "json").strip().lower()
    return TextFormatter() if chosen == "text" else JsonFormatter()


def configure_logging(level: int = logging.INFO, *, root: logging.Logger | None = None) -> bool:
    """Install the Carvis handler on the root logger unless something already configured logging.

    Returns whether a handler was installed. As before, existing handlers (a test harness, or a
    deployment's own logging configuration) are left alone. ``root`` exists for tests.
    """
    root = logging.getLogger() if root is None else root
    if root.handlers:
        return False
    handler = logging.StreamHandler()
    handler.setFormatter(formatter_from_environment())
    root.addHandler(handler)
    root.setLevel(level)
    return True
