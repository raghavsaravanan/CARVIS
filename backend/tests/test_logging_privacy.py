"""M2 Track A6: generic 503s without exception text, and logs that never carry conversation content.

The log-capture tests drive the real request paths with a distinctive canary in the spoken question
and assert it reaches no log record, at any level, from any logger. Nothing contacts a provider.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
from unittest.mock import AsyncMock

import pytest

import log_config
import main
from log_config import FORBIDDEN_FIELDS, JsonFormatter, TextFormatter, configure_logging, log_event
from tests.test_conversation import JPEG, SECRET, Phone, api, client, confirmed, payload, vapi  # noqa: F401

CANARY = "zqxcanary"
QUESTION = f"ride height tolerance {CANARY}"
INTERNAL = "VISION_API_KEY is not configured at https://internal.invalid/v1"
VISION_FORM = {"session_id": "s-1", "year": "2022", "make": "subaru", "model": "wrx"}


def run(coro):
    return asyncio.run(coro)


def everything_logged(caplog) -> str:
    """Rendered messages plus structured fields and exception text of every captured record."""
    parts = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(getattr(record, "carvis_fields", None)))
        if record.exc_info:
            parts.append(logging.Formatter().formatException(record.exc_info))
    return "\n".join(parts)


# --- Generic 503s ----------------------------------------------------------------------------------


def test_vision_query_failure_is_a_generic_503(api, monkeypatch, caplog):
    monkeypatch.setattr(main, "identify_component", AsyncMock(side_effect=main.VisionConfigurationError(INTERNAL)))

    async def scenario():
        async with client() as http:
            # "what is this" names no component, so the photo must be identified.
            return await http.post("/vision-query", files={"file": ("f.jpg", JPEG, "image/jpeg")},
                                   data={"question": "what is this part", **VISION_FORM})
    with caplog.at_level(logging.DEBUG):
        response = run(scenario())
    assert response.status_code == 503
    assert response.json() == {"detail": main.VISION_UNAVAILABLE_DETAIL}
    assert "internal.invalid" not in response.text and "VISION_API_KEY" not in response.text
    assert INTERNAL in caplog.text, "the reason must still reach the server log"


def test_camera_photo_failure_is_a_generic_503(api, monkeypatch):
    async def failing(*args, **kwargs):
        raise main.VisionConfigurationError(INTERNAL)
    monkeypatch.setattr(main.conversation_tools, "receive_photo", failing)

    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            return await http.post(f"/conversation/sessions/{phone.id}/camera/r-1/photo", headers=phone.auth,
                                   files={"file": ("f.jpg", JPEG, "image/jpeg")})
    response = run(scenario())
    assert response.status_code == 503
    assert response.json() == {"detail": main.VISION_UNAVAILABLE_DETAIL}
    assert "internal.invalid" not in response.text


def test_legacy_tool_call_never_speaks_exception_text(monkeypatch):
    def failing(*args, **kwargs):
        raise RuntimeError(INTERNAL)
    monkeypatch.setattr(main, "_search_top_chunk_sync", failing)
    call = {"id": "call-1", "function": {"arguments": json.dumps(
        {"query": "ride height", "year": "2022", "make": "subaru", "model": "wrx"})}}
    answer = main.handle_tool_call(call, 0, client=None, embedder=None)
    assert answer.ok is False
    assert answer.error == main.LOOKUP_UNAVAILABLE_DETAIL
    assert "internal.invalid" not in repr(answer)


def test_unexpected_lookup_failure_is_a_generic_503(api, monkeypatch):
    monkeypatch.setattr(main, "search_top_chunk", AsyncMock(side_effect=RuntimeError(INTERNAL)))

    async def scenario():
        async with client() as http:
            return await http.post("/vision-query", files={"file": ("f.jpg", JPEG, "image/jpeg")},
                                   data={"question": "ride height tolerance", **VISION_FORM})
    response = run(scenario())
    assert response.status_code == 503
    assert response.json() == {"detail": main.LOOKUP_UNAVAILABLE_DETAIL}
    assert "internal.invalid" not in response.text


# --- No conversation content in logs ---------------------------------------------------------------


def test_legacy_vapi_lookup_never_logs_the_question(api, caplog):
    body = {"message": {"toolCallList": [{"id": "call-1", "function": {"arguments": json.dumps(
        {"query": QUESTION, "year": "2022", "make": "subaru", "model": "wrx"})}}]}}

    async def scenario():
        async with client() as http:
            return await http.post("/vapi-tool", json=body, headers={"x-vapi-secret": SECRET})
    with caplog.at_level(logging.DEBUG):
        response = run(scenario())
    assert response.status_code == 200
    events = [r for r in caplog.records if r.getMessage().startswith("vapi_tool")]
    assert [r.getMessage() for r in events] == ["vapi_tool inbound", "vapi_tool outcome"]
    assert events[0].carvis_fields["query_chars"] == len(QUESTION)
    assert CANARY not in everything_logged(caplog)


def test_conversation_lookup_never_logs_the_question(api, caplog):
    async def scenario():
        async with client() as http:
            await confirmed(http)
            return await vapi(http, ("c-1", "lookup_spec", {"query": QUESTION}))
    with caplog.at_level(logging.DEBUG):
        [entry] = run(scenario())
    assert payload(entry)["status"]
    assert caplog.records, "the path must actually log something for this test to mean anything"
    assert CANARY not in everything_logged(caplog)


def test_vision_query_never_logs_the_question(api, caplog):
    async def scenario():
        async with client() as http:
            return await http.post("/vision-query", files={"file": ("f.jpg", JPEG, "image/jpeg")},
                                   data={"question": QUESTION, **VISION_FORM})
    with caplog.at_level(logging.DEBUG):
        run(scenario())
    assert any("vision-query timings_ms" in r.getMessage() for r in caplog.records), "the path must log"
    assert CANARY not in everything_logged(caplog)


def test_refused_answer_numbers_stay_in_the_trace_but_not_the_log(caplog):
    """The trace is the phone's own diagnostic view; the server log keeps only counts and codes."""
    import conversation
    from spec_schema import Vehicle
    session, _ = conversation.ConversationStore().create(
        "Gabriel", Vehicle(shop_id="shop_demo", year="2022", make="subaru", model="wrx"))
    with caplog.at_level(logging.DEBUG):
        session.note("speech_rejected", numbers=["987.65"], request_id="r-1")
    assert session.trace[-1]["numbers"] == ["987.65"]
    [record] = [r for r in caplog.records if r.getMessage() == "conversation speech_rejected"]
    assert record.carvis_fields["request_id"] == "r-1"
    assert record.carvis_fields["dropped_fields"] == ["numbers"]
    assert "987.65" not in everything_logged(caplog)


def test_spacetimedb_error_body_is_not_logged(monkeypatch, caplog):
    """The reducer arguments carry the question, so an echoing error body must not be logged."""
    class Response:
        status_code = 500
        text = f"bad request for {QUESTION}"

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return Response()
    monkeypatch.setattr(main, "SPACETIMEDB_URI", "https://stdb.invalid")
    monkeypatch.setattr(main, "SPACETIMEDB_DB_NAME", "carvis-test")
    monkeypatch.setattr(main, "SPACETIMEDB_TOKEN", "test-only-token")
    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    with caplog.at_level(logging.DEBUG):
        run(main._spacetime_call_reducer("start_shop_query", ["q", "s", "2022", "subaru", "wrx", QUESTION]))
    assert "returned 500" in caplog.text
    assert CANARY not in everything_logged(caplog)
    assert "test-only-token" not in everything_logged(caplog)


# --- Scaffold --------------------------------------------------------------------------------------


def make_record(fields=None, exc=None, message="vapi_tool outcome"):
    record = logging.LogRecord("carvis.main", logging.INFO, __file__, 1, message, None, exc)
    if fields is not None:
        record.carvis_fields = fields
    return record


def test_json_formatter_emits_one_object_per_line():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        line = JsonFormatter().format(make_record({"outcome": "ok", "elapsed_ms": 1.5}, sys.exc_info()))
    entry = json.loads(line)
    assert "\n" not in line
    assert entry["level"] == "INFO" and entry["logger"] == "carvis.main"
    assert entry["message"] == "vapi_tool outcome"
    assert entry["fields"] == {"outcome": "ok", "elapsed_ms": 1.5}
    assert entry["exc_type"] == "ValueError"
    assert entry["ts"].endswith("+00:00")


def test_text_formatter_appends_fields():
    line = TextFormatter().format(make_record({"outcome": "ok"}))
    assert line.endswith("vapi_tool outcome outcome='ok'")


@pytest.mark.parametrize("name", sorted(FORBIDDEN_FIELDS))
def test_log_event_drops_content_bearing_fields(caplog, name):
    logger = logging.getLogger("carvis.test")
    with caplog.at_level(logging.INFO, logger="carvis.test"):
        log_event(logger, logging.INFO, "event", **{name: QUESTION, "outcome": "ok"})
    [record] = caplog.records
    assert record.carvis_fields == {"outcome": "ok", "dropped_fields": [name]}
    assert CANARY not in everything_logged(caplog)


@pytest.mark.parametrize("name, dropped", [
    ("query_preview", True), ("spoken_answer", True), ("raw-transcript", True), ("Question", True),
    ("query_chars", False), ("image_bytes", False), ("tool_call_id", False), ("messages_count", False),
    ("outcome", False), ("shop_id", False),
])
def test_content_field_names(name, dropped):
    assert log_config.is_content_field(name) is dropped


def test_log_event_drops_regardless_of_case(caplog):
    with caplog.at_level(logging.INFO, logger="carvis.test"):
        log_event(logging.getLogger("carvis.test"), logging.INFO, "event", Transcript=QUESTION)
    assert caplog.records[0].carvis_fields == {"dropped_fields": ["Transcript"]}


@pytest.fixture
def bare_root():
    """A stand-in root logger with no handlers (pytest attaches its own handlers to the real root)."""
    return logging.Logger("carvis-test-root")


@pytest.mark.parametrize("setting, formatter", [(None, JsonFormatter), ("json", JsonFormatter),
                                                ("TEXT", TextFormatter), ("unknown", JsonFormatter)])
def test_configure_logging_installs_the_chosen_format(bare_root, monkeypatch, setting, formatter):
    if setting is None:
        monkeypatch.delenv(log_config.LOG_FORMAT_ENV, raising=False)
    else:
        monkeypatch.setenv(log_config.LOG_FORMAT_ENV, setting)
    assert configure_logging(root=bare_root) is True
    [handler] = bare_root.handlers
    assert type(handler.formatter) is formatter
    assert configure_logging(root=bare_root) is False, "a second call must not add another handler"
    assert len(bare_root.handlers) == 1


def test_configure_logging_leaves_existing_configuration_alone(bare_root):
    existing = logging.StreamHandler(io.StringIO())
    bare_root.addHandler(existing)
    assert configure_logging(root=bare_root) is False
    assert bare_root.handlers == [existing]
