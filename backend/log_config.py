"""Structured logging scaffold for the Carvis API (M2 Track A6).

Logs are one JSON object per line (``CARVIS_LOG_FORMAT=text`` keeps the human-readable format for
local work). Structured fields go through :func:`log_event`, which refuses field names that would
carry conversation content: transcripts, spoken questions, answers and image bytes are never logged.
Request IDs, call IDs and metrics arrive with Track B1 on top of this scaffold
(``docs/architecture/09-deployment-operations.md``).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

LOG_FORMAT_ENV = "CARVIS_LOG_FORMAT"
TEXT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

FORBIDDEN_FIELDS = frozenset({
    "answer", "artifact", "audio", "image", "message", "messages", "numbers", "prompt", "query",
    "question", "spoken", "text", "transcript", "utterance",
})
"""Words that mark a field as conversation content. :func:`log_event` drops such fields."""

MEASURE_SUFFIXES = frozenset({"bytes", "chars", "count", "id", "ids", "len", "length"})
"""A final name part that makes a field a measurement or identifier, such as ``query_chars``."""


def is_content_field(name: str) -> bool:
    """Whether ``name`` would carry content: ``query``, ``query_preview`` and ``Transcript`` would."""
    parts = [part for part in name.lower().replace("-", "_").split("_") if part]
    if not parts or parts[-1] in MEASURE_SUFFIXES:
        return False
    return any(part in FORBIDDEN_FIELDS for part in parts)

_FIELDS_ATTR = "carvis_fields"


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Log ``event`` with structured ``fields``; content-bearing field names are dropped, never logged.

    Values should be identifiers, counts, codes, durations or vehicle attributes. A dropped name is
    reported in ``dropped_fields`` so the offending call site is easy to find.
    """
    safe = {key: value for key, value in fields.items() if not is_content_field(key)}
    dropped = sorted(set(fields) - set(safe))
    if dropped:
        safe["dropped_fields"] = dropped
    logger.log(level, event, extra={_FIELDS_ATTR: safe})


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
