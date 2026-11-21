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
from log_config import FIELD_POLICY, REDACTED, JsonFormatter, TextFormatter, configure_logging, log_event, safe_fields
from tests.test_conversation import JPEG, SECRET, Phone, api, client, confirmed, payload, vapi, webhook  # noqa: F401

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
    # The server log keeps the error type and code, never the exception message.
    [record] = [r for r in caplog.records if r.getMessage() == "vision unavailable"]
    assert record.carvis_fields == {"error": "VisionConfigurationError", "code": "vision_unavailable", "setting": None}
    assert "internal.invalid" not in everything_logged(caplog)


def test_missing_vision_setting_is_logged_by_name_not_message(monkeypatch, caplog):
    monkeypatch.setattr(main, "VISION_PROVIDER", "nemotron")
    monkeypatch.setattr(main, "_VISION_CLIENT", None)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with caplog.at_level(logging.DEBUG), pytest.raises(main.VisionConfigurationError) as raised:
        run(main.identify_component(JPEG, "what is this", "2022", "subaru", "wrx"))
    assert (raised.value.code, raised.value.setting) == ("not_configured", "NVIDIA_API_KEY")


def test_camera_photo_failure_is_a_generic_503(api, monkeypatch, caplog):
    async def failing(*args, **kwargs):
        raise main.VisionConfigurationError(INTERNAL)
    monkeypatch.setattr(main.conversation_tools, "receive_photo", failing)

    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            return await http.post(f"/conversation/sessions/{phone.id}/camera/r-1/photo", headers=phone.auth,
                                   files={"file": ("f.jpg", JPEG, "image/jpeg")})
    with caplog.at_level(logging.DEBUG):
        response = run(scenario())
    assert response.status_code == 503
    assert response.json() == {"detail": main.VISION_UNAVAILABLE_DETAIL}
    assert "internal.invalid" not in response.text
    assert any(r.getMessage() == "vision unavailable" for r in caplog.records)
    assert "internal.invalid" not in everything_logged(caplog)


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
        session.note("speech_rejected", numbers=["987.65"], request_id="0" * 32)
    assert session.trace[-1]["numbers"] == ["987.65"]
    [record] = [r for r in caplog.records if getattr(r, "carvis_fields", {}).get("stage") == "speech_rejected"]
    assert record.carvis_fields["request_id"] == "0" * 32
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


def test_only_permitted_fields_are_logged(caplog):
    with caplog.at_level(logging.INFO, logger="carvis.test"):
        log_event(logging.getLogger("carvis.test"), logging.INFO, "event", outcome="ok", query=QUESTION,
                  query_preview=QUESTION, transcript=QUESTION, anything_else=1)
    [record] = caplog.records
    assert record.carvis_fields == {"outcome": "ok",
                                    "dropped_fields": ["anything_else", "query", "query_preview", "transcript"]}
    assert CANARY not in everything_logged(caplog)


@pytest.mark.parametrize("name, value", [
    ("reason", QUESTION), ("reason", CANARY), ("component", QUESTION), ("component", CANARY),
    ("operation", CANARY), ("code", QUESTION), ("outcome", "Not A Code"), ("error", "bad message: x"),
    ("score", "0.9"), ("changed", [QUESTION]), ("changed", [CANARY]), ("changed", {"make": "x"}),
    ("session", {"nested": QUESTION}), ("session", CANARY), ("request_id", f"{CANARY}-{'0' * 23}"),
    ("setting", CANARY), ("tool", CANARY), ("tool", "what.is.the.torque:for-the-zqxcanary_bolts"),
    ("reason", "vehicle corrected: zqxcanary"), ("reason", f"vehicle corrected: make, {CANARY}"),
    ("bytes", [1, 2]), ("shop_id", {"nested": CANARY}),
])
def test_permitted_fields_redact_values_that_fail_validation(name, value):
    fields = safe_fields({name: value})
    assert fields == {name: REDACTED, "redacted_fields": [name]}


@pytest.mark.parametrize("name, value", [
    ("reason", "vapi end-of-call-report"), ("reason", "vehicle corrected: make, model"), ("component", "oil_filter"),
    ("operation", "installation"), ("spec_type", "torque"), ("code", "camera_timeout"), ("error", "TimeoutError"),
    ("request_id", "3f5e0c1a9b7d4c2e8f105a6b7c8d9e0f"), ("session", "3f5e0c1a"), ("score", 0.91),
    ("has_vehicle", True), ("changed", ["make", "model"]), ("component", None), ("tool", "lookup_spec"),
    ("setting", "NVIDIA_API_KEY"), ("reason", "vehicle corrected: make, transmission"),
    ("shop_id", main.DEFAULT_SHOP_ID), ("vapi_call_id", None),
])
def test_valid_values_pass(name, value):
    assert safe_fields({name: value}) == {name: value}


@pytest.mark.parametrize("name", ["shop_id", "tool_call_id", "vapi_call_id"])
@pytest.mark.parametrize("value", [QUESTION, CANARY, "what.is.the.torque:for-the-zqxcanary_bolts"],
                         ids=["sentence", "token", "joined"])
def test_caller_supplied_identifiers_are_fingerprinted(name, value):
    logged = safe_fields({name: value})[name]
    assert logged.startswith(log_config.FINGERPRINT_PREFIX) and len(logged) == 15
    assert CANARY not in logged
    assert safe_fields({name: value})[name] == logged, "stable within the process, so lines correlate"
    assert safe_fields({name: value + "x"})[name] != logged


def test_fingerprints_differ_across_fields():
    """The same value must not link a shop_id line to a tool-call or call-ID line."""
    logged = {safe_fields({name: CANARY})[name] for name in ("shop_id", "tool_call_id", "vapi_call_id")}
    assert len(logged) == 3


def test_fingerprints_are_salted_per_process():
    """A fixed or empty key would let anyone confirm a guessed ID by hashing it; a random per-process
    salt means the same ID fingerprints differently in another process."""
    import subprocess
    import sys
    from pathlib import Path
    backend = Path(log_config.__file__).parent
    code = f"import log_config; print(log_config.fingerprint({CANARY!r}))"
    others = {subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True,
                             check=True).stdout.strip() for _ in range(2)}
    assert len(others) == 2 and log_config.fingerprint(CANARY) not in others


def test_every_policy_field_has_a_validator():
    assert FIELD_POLICY and all(callable(validator) for validator in FIELD_POLICY.values())


def test_only_vocabulary_fields_can_be_registered():
    with pytest.raises(ValueError):
        log_config.register_values("session", ["anything"])


# --- Canaries in non-query fields ------------------------------------------------------------------


def camera_request(http, phone):
    waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
    return waiting


def test_camera_unavailable_reason_stays_in_the_trace_not_the_log(api, caplog):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = camera_request(http, phone)
            command = await phone.next_command()
            response = await http.post(f"/conversation/sessions/{phone.id}/camera/{command['request_id']}/failure",
                                       headers=phone.auth, json={"reason": QUESTION})
            assert response.status_code == 200
            await waiting
            return await phone.state()
    with caplog.at_level(logging.DEBUG):
        state = run(scenario())
    assert any(note.get("reason") == QUESTION for note in state["trace"]), "the phone's trace is unchanged"
    [record] = [r for r in caplog.records if getattr(r, "carvis_fields", {}).get("stage") == "camera_unavailable"]
    assert record.carvis_fields["reason"] == REDACTED
    assert CANARY not in everything_logged(caplog)


@pytest.mark.parametrize("reason", [QUESTION, CANARY], ids=["sentence", "single-token"])
def test_phone_supplied_call_end_reason_is_not_logged(api, caplog, reason):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            assert (await phone.end(reason=reason)).status_code == 200
            return await phone.state()
    with caplog.at_level(logging.DEBUG):
        state = run(scenario())
    assert any(note.get("reason") == reason for note in state["trace"])
    assert CANARY not in everything_logged(caplog)


def test_ios_call_end_reason_is_still_logged(api, caplog):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            await phone.end(reason="app")
    with caplog.at_level(logging.DEBUG):
        run(scenario())
    [record] = [r for r in caplog.records if getattr(r, "carvis_fields", {}).get("stage") == "call_ended"]
    assert record.carvis_fields["reason"] == "app"


def test_model_supplied_work_context_is_not_logged(api, caplog):
    async def scenario():
        async with client() as http:
            await confirmed(http)
            await vapi(http, ("c-1", "set_work_context", {"component": QUESTION, "operation": CANARY}))
    with caplog.at_level(logging.DEBUG):
        run(scenario())
    [record] = [r for r in caplog.records if getattr(r, "carvis_fields", {}).get("stage") == "work_context"]
    assert record.carvis_fields["component"] == record.carvis_fields["operation"] == REDACTED
    assert CANARY not in everything_logged(caplog)


def test_vision_model_output_is_not_logged(api, caplog):
    api.return_value = {"component": QUESTION, "confidence": 0.7, "visual_context": QUESTION,
                        "uncertainty": QUESTION}

    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = camera_request(http, phone)
            command = await phone.next_command()
            assert (await phone.photo(command["request_id"])).status_code == 200
            await waiting
    with caplog.at_level(logging.DEBUG):
        run(scenario())
    assert any(getattr(r, "carvis_fields", {}).get("stage") == "vision_done" for r in caplog.records)
    assert CANARY not in everything_logged(caplog)


def test_vehicle_summary_is_not_logged(api, caplog):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start(trim=f"Limited {CANARY}")
    with caplog.at_level(logging.DEBUG):
        run(scenario())
    assert any(getattr(r, "carvis_fields", {}).get("stage") == "session_created" for r in caplog.records)
    assert CANARY not in everything_logged(caplog)


def test_legacy_webhook_free_form_fields_are_not_logged(api, caplog):
    body = {"message": {"toolCallList": [{"id": f"call {CANARY}", "function": {"arguments": json.dumps(
        {"query": "ride height tolerance", "year": "2022", "make": f"subaru {CANARY}", "model": CANARY,
         "shop_id": f"shop {CANARY}"})}}]}, f"extra {CANARY}": {"nested": CANARY}}

    async def scenario():
        async with client() as http:
            return await http.post("/vapi-tool", json=body, headers={"x-vapi-secret": SECRET})
    with caplog.at_level(logging.DEBUG):
        assert run(scenario()).status_code == 200
    assert any(r.getMessage() == "vapi_tool outcome" for r in caplog.records)
    assert CANARY not in everything_logged(caplog)


def test_unknown_tool_names_are_not_logged(api, caplog):
    """A stale or duplicate tool call is noted before its name is checked against the known tools."""
    joined = "torque-the-caliper-bolts-zqxcanary-please"

    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            await vapi(http, ("dup-1", "set_work_context", {"component": "oil_filter"}))
            await vapi(http, ("dup-1", joined, {}))          # duplicate toolCallId, unknown name
            await phone.end()
            await http.post("/vapi-tool", json=webhook((f"late-{CANARY}", joined, {})),
                            headers={"x-vapi-secret": SECRET})  # stale call
    with caplog.at_level(logging.DEBUG):
        run(scenario())
    stages = {r.carvis_fields.get("stage") for r in caplog.records if hasattr(r, "carvis_fields")}
    assert {"tool_duplicate", "tool_rejected_stale"} <= stages
    assert CANARY not in everything_logged(caplog)


@pytest.mark.parametrize("call_id", [QUESTION, CANARY, "what.is.the.torque:for-the-zqxcanary_bolts"],
                         ids=["sentence", "token", "joined"])
def test_phone_and_webhook_call_ids_are_fingerprinted(api, caplog, call_id):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id=call_id)                      # phone bind
            other = Phone(http)
            await other.start()
            await other.call(vapi_call_id=None)
            await http.post("/vapi-tool", headers={"x-vapi-secret": SECRET}, json=webhook(
                ("c-1", "confirm_vehicle", {"year": "2022", "make": "subaru", "model": "wrx"}),
                call_id=f"{call_id}-auto", variables=other.variables))  # webhook auto-bind
    with caplog.at_level(logging.DEBUG):
        run(scenario())
    bound = [r.carvis_fields for r in caplog.records if getattr(r, "carvis_fields", {}).get("stage") == "call_bound"]
    assert bound and all(f["vapi_call_id"].startswith("fp:") for f in bound)
    assert CANARY not in everything_logged(caplog)


@pytest.mark.parametrize("value", [CANARY, "what.is.the.torque:for-the-zqxcanary_bolts"], ids=["token", "joined"])
def test_legacy_single_token_identifiers_are_not_logged(api, caplog, value):
    body = {"message": {"toolCallList": [{"id": value, "function": {"arguments": json.dumps(
        {"query": "ride height tolerance", "year": "2022", "make": "subaru", "model": "wrx",
         "shop_id": value})}}]}}

    async def scenario():
        async with client() as http:
            return await http.post("/vapi-tool", json=body, headers={"x-vapi-secret": SECRET})
    with caplog.at_level(logging.DEBUG):
        assert run(scenario()).status_code == 200
    [inbound] = [r.carvis_fields for r in caplog.records if r.getMessage() == "vapi_tool inbound"]
    assert inbound["shop_id"].startswith("fp:") and inbound["tool_call_id"].startswith("fp:")
    assert CANARY not in everything_logged(caplog)


def test_spoken_variant_correction_reason_is_still_logged(caplog):
    import conversation
    from spec_schema import Vehicle
    session, _ = conversation.ConversationStore().create(
        "Gabriel", Vehicle(shop_id="shop_demo", year="2022", make="subaru", model="wrx", transmission="6mt"))
    with caplog.at_level(logging.DEBUG):
        session.invalidate_work("vehicle corrected: transmission")
    [record] = [r for r in caplog.records if getattr(r, "carvis_fields", {}).get("stage") == "memory_invalidated"]
    assert record.carvis_fields["reason"] == "vehicle corrected: transmission"


def test_upload_job_failure_logs_the_type_not_the_message(monkeypatch, caplog, tmp_path):
    async def failing(*args, **kwargs):
        raise RuntimeError(f"LlamaParse said: {QUESTION}")
    monkeypatch.setattr(main, "run_ingest", failing)
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with caplog.at_level(logging.DEBUG):
        run(main._ingest_upload_job(pdf, "2022", "subaru", "wrx", "shop_demo", client=None, embedder=None))
    [record] = [r for r in caplog.records if r.getMessage() == "upload job failed"]
    assert record.carvis_fields == {"error": "RuntimeError", "shop_id": "shop_demo"}
    assert not record.exc_info, "no traceback: it would carry the exception message"
    assert CANARY not in everything_logged(caplog)


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
