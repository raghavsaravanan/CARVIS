"""M2 Track A1: the Vapi tool webhook fails closed.

Request level: /vapi-tool authorizes only an exact, constant-time match of ``X-Vapi-Secret``
against a configured secret; unset or blank configuration rejects everything, and a rejected
request reaches no handler. Boot level: every environment other than ``local`` refuses to start
without a secret, before any model or Qdrant work. Behavior with a correct secret is unchanged.
"""
from __future__ import annotations

import asyncio
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import conversation
import main
import webhook_auth
from webhook_auth import WebhookConfigurationError

SECRET = "carvis-test-secret-0123456789"
UNAUTHORIZED = {"detail": "Unauthorized"}


def run(coro):
    return asyncio.run(coro)


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://carvis", timeout=30)


def tool_calls_payload():
    arguments = json.dumps({"year": "2022", "make": "subaru", "model": "wrx"})
    return {"message": {"type": "tool-calls", "call": {"id": "vapi-auth-1"},
                        "toolCallList": [{"id": "tc-1", "type": "function",
                                          "function": {"name": "confirm_vehicle", "arguments": arguments}}]}}


def ended_payload():
    return {"message": {"type": "status-update", "status": "ended", "call": {"id": "vapi-auth-1"}}}


@pytest.fixture
def spies(monkeypatch):
    """Record whether a request got past authentication into any webhook handler."""
    for name in ("CARVIS_ENV", "RENDER", "VAPI_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    store = conversation.ConversationStore()
    session_for_webhook = MagicMock(wraps=store.session_for_webhook)
    handle_call_event = MagicMock(wraps=store.handle_call_event)
    monkeypatch.setattr(store, "session_for_webhook", session_for_webhook)
    monkeypatch.setattr(store, "handle_call_event", handle_call_event)
    monkeypatch.setattr(main, "conversations", store)
    lookup = AsyncMock(side_effect=AssertionError("legacy lookup must not run in these tests"))
    monkeypatch.setattr(main, "search_top_chunk", lookup)
    return {"session_for_webhook": session_for_webhook, "handle_call_event": handle_call_event, "lookup": lookup}


def assert_untouched(spies):
    assert not spies["session_for_webhook"].called
    assert not spies["handle_call_event"].called
    assert not spies["lookup"].called


async def post(http, headers=None, payload=None, content=None):
    if content is not None:
        return await http.post("/vapi-tool", content=content, headers={"content-type": "application/json", **(headers or {})})
    return await http.post("/vapi-tool", json=payload or tool_calls_payload(), headers=headers or {})


# --- Request level -----------------------------------------------------------------------------


@pytest.mark.parametrize("configured", [None, "", "   ", "\t\n"], ids=["unset", "empty", "spaces", "whitespace"])
def test_unconfigured_secret_rejects_every_request(spies, monkeypatch, configured):
    """Previously the webhook skipped authentication entirely when no secret was configured."""
    if configured is not None:
        monkeypatch.setenv("VAPI_WEBHOOK_SECRET", configured)

    async def scenario():
        async with client() as http:
            presented = [None, "", "anything", SECRET]
            if configured and configured.strip():
                presented.append(configured)
            for value in presented:
                headers = {} if value is None else {"x-vapi-secret": value}
                for payload in (tool_calls_payload(), ended_payload()):
                    response = await post(http, headers, payload)
                    assert response.status_code == 401, (value, response.text)
                    assert response.json() == UNAUTHORIZED
    run(scenario())
    assert_untouched(spies)


@pytest.mark.parametrize("presented", [
    None, "", " ", "wrong", SECRET[:-1], SECRET + "x", SECRET.upper(), f"Bearer {SECRET}", SECRET[1:], "x" * 4096,
], ids=["missing", "empty", "space", "wrong", "prefix", "suffix", "case", "bearer", "truncated", "long"])
def test_wrong_secret_is_rejected_before_any_handler(spies, monkeypatch, presented):
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)

    async def scenario():
        async with client() as http:
            headers = {} if presented is None else {"x-vapi-secret": presented}
            for payload in (tool_calls_payload(), ended_payload()):
                response = await post(http, headers, payload)
                assert response.status_code == 401
                assert response.json() == UNAUTHORIZED
    run(scenario())
    assert_untouched(spies)


def test_secret_in_another_header_is_rejected(spies, monkeypatch):
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)

    async def scenario():
        async with client() as http:
            for headers in ({"authorization": f"Bearer {SECRET}"}, {"x-vapi-signature": SECRET},
                            {"x-call-id": SECRET}):
                assert (await post(http, headers)).status_code == 401
            assert (await http.post(f"/vapi-tool?secret={SECRET}", json=tool_calls_payload())).status_code == 401
    run(scenario())
    assert_untouched(spies)


def test_non_ascii_header_is_a_401_not_a_server_error(spies, monkeypatch):
    """hmac.compare_digest raises TypeError on non-ASCII str; attacker input must never 500."""
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)

    async def scenario():
        async with client() as http:
            for raw in ("été".encode("latin-1"), "sécret".encode("utf-8"), b"\xff\xfe"):
                response = await post(http, {"x-vapi-secret": raw})
                assert response.status_code == 401
                assert response.json() == UNAUTHORIZED
    run(scenario())
    assert_untouched(spies)


def test_authentication_precedes_body_parsing(spies, monkeypatch):
    """An unauthenticated caller can't probe the parser; it gets 401, not the Vapi-shaped 200."""
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)

    async def scenario():
        async with client() as http:
            for body in (b"{not json", b"[]", b""):
                assert (await post(http, {"x-vapi-secret": "wrong"}, content=body)).status_code == 401
            # The authorized behavior for malformed bodies is unchanged.
            response = await post(http, {"x-vapi-secret": SECRET}, content=b"{not json")
            assert response.status_code == 200
            assert response.json()["results"][0]["error"] == "Request body must be valid JSON."
    run(scenario())
    assert_untouched(spies)


def test_correct_secret_is_processed_unchanged(spies, monkeypatch):
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)

    async def scenario():
        async with client() as http:
            response = await post(http, {"x-vapi-secret": SECRET})
            assert response.status_code == 200, response.text
            [entry] = response.json()["results"]
            assert entry["toolCallId"] == "tc-1"
            assert json.loads(entry["result"])["status"] == "no_session"
            # Header names are case-insensitive, as before.
            ended = await post(http, {"X-Vapi-Secret": SECRET}, ended_payload())
            assert ended.status_code == 200 and ended.json() == {}
    run(scenario())
    assert spies["session_for_webhook"].called
    assert spies["handle_call_event"].call_count == 1
    assert not spies["lookup"].called


def test_configured_secret_is_trimmed_as_before(spies, monkeypatch):
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", f"  {SECRET}\n")

    async def scenario():
        async with client() as http:
            assert (await post(http, {"x-vapi-secret": SECRET})).status_code == 200
    run(scenario())


def test_secret_rotation_takes_effect_without_restart(spies, monkeypatch):
    """The secret is read per request, as before; the old value stops working immediately."""
    async def scenario():
        async with client() as http:
            monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)
            assert (await post(http, {"x-vapi-secret": SECRET})).status_code == 200
            monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "rotated-secret")
            assert (await post(http, {"x-vapi-secret": SECRET})).status_code == 401
            assert (await post(http, {"x-vapi-secret": "rotated-secret"})).status_code == 200
            monkeypatch.delenv("VAPI_WEBHOOK_SECRET")
            assert (await post(http, {"x-vapi-secret": "rotated-secret"})).status_code == 401
    run(scenario())


def test_comparison_is_constant_time(spies, monkeypatch):
    """Guards against a regression to ``==``/``!=``; timing itself is not measurable in a unit test."""
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)
    real = hmac.compare_digest
    compare = MagicMock(side_effect=real)
    monkeypatch.setattr(webhook_auth.hmac, "compare_digest", compare)

    async def scenario():
        async with client() as http:
            assert (await post(http, {"x-vapi-secret": "wrong"})).status_code == 401
            assert (await post(http, {"x-vapi-secret": SECRET})).status_code == 200
    run(scenario())
    # hmac is process-wide; consider only comparisons against the webhook secret.
    webhook_calls = [args for args, _ in compare.call_args_list if SECRET.encode() in args]
    assert len(webhook_calls) == 2
    assert all(isinstance(value, bytes) for args in webhook_calls for value in args)


def test_other_routes_do_not_require_the_webhook_secret(spies):
    """Scope guard: A1 changes only /vapi-tool; liveness stays open with no secret configured."""
    async def scenario():
        async with client() as http:
            assert (await http.get("/health")).status_code == 200
    run(scenario())


# --- Boot level --------------------------------------------------------------------------------


class FakeQdrant:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def collection_exists(self, name):
        return True

    def close(self):
        self.closed = True


@pytest.fixture
def boot(monkeypatch):
    """Run the real lifespan with the embedding model and Qdrant faked; never touches a provider."""
    for name in ("CARVIS_ENV", "RENDER", "VAPI_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.invalid")
    monkeypatch.setenv("QDRANT_API_KEY", "test-only")
    embedder = MagicMock(name="TextEmbedding")
    monkeypatch.setattr(main, "TextEmbedding", embedder)
    monkeypatch.setattr(main, "QdrantClient", FakeQdrant)
    # The lifespan replaces app.state, closes the vision client and sets the logger level;
    # restore whatever other tests installed.
    for name in ("qdrant", "embedder"):
        monkeypatch.setattr(main.app.state, name, getattr(main.app.state, name, None), raising=False)
    monkeypatch.setattr(main, "_VISION_CLIENT", None)
    level = main.logger.level

    async def start():
        async with main.lifespan(main.app):
            return main.app.state.qdrant

    def boot_once():
        return run(start())

    boot_once.embedder = embedder
    yield boot_once
    main.logger.setLevel(level)


@pytest.mark.parametrize("environment", [None, "", "production", "staging", "PRODUCTION", " Staging "])
@pytest.mark.parametrize("configured", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_boot_refuses_outside_local_without_a_secret(boot, monkeypatch, environment, configured):
    if environment is not None:
        monkeypatch.setenv("CARVIS_ENV", environment)
    if configured is not None:
        monkeypatch.setenv("VAPI_WEBHOOK_SECRET", configured)
    with pytest.raises(WebhookConfigurationError, match="VAPI_WEBHOOK_SECRET is required"):
        boot()
    assert not boot.embedder.called, "the check must run before models or Qdrant load"


@pytest.mark.parametrize("environment", ["prod", "dev", "test", "locale", "local,production"])
def test_boot_refuses_an_unknown_environment(boot, monkeypatch, environment):
    """A typo must not silently select a weaker mode, even with a secret set."""
    monkeypatch.setenv("CARVIS_ENV", environment)
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)
    with pytest.raises(WebhookConfigurationError, match="CARVIS_ENV must be one of"):
        boot()
    assert not boot.embedder.called


def test_render_cannot_claim_to_be_local(boot, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("CARVIS_ENV", "local")
    with pytest.raises(WebhookConfigurationError, match="not allowed on Render"):
        boot()
    assert not boot.embedder.called


@pytest.mark.parametrize("environment", [None, "production", "staging"])
def test_boot_with_a_secret_is_unchanged(boot, monkeypatch, environment):
    if environment is not None:
        monkeypatch.setenv("CARVIS_ENV", environment)
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)
    client = boot()
    assert isinstance(client, FakeQdrant) and client.closed
    assert boot.embedder.called


def test_render_with_a_secret_boots(boot, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)
    assert isinstance(boot(), FakeQdrant)


def test_local_boots_without_a_secret_but_the_webhook_stays_closed(boot, spies, monkeypatch, caplog):
    monkeypatch.setenv("CARVIS_ENV", "local")
    with caplog.at_level("WARNING", logger="carvis.main"):
        assert isinstance(boot(), FakeQdrant)
    assert "will reject every request" in caplog.text

    async def scenario():
        async with client() as http:
            for headers in ({}, {"x-vapi-secret": ""}, {"x-vapi-secret": "anything"}):
                assert (await post(http, headers)).status_code == 401
    run(scenario())
    assert_untouched(spies)


def test_boot_refusal_does_not_echo_a_misplaced_secret(boot, monkeypatch):
    monkeypatch.setenv("CARVIS_ENV", SECRET)
    with pytest.raises(WebhookConfigurationError) as exc:
        boot()
    assert SECRET not in str(exc.value)


def test_emitted_boot_errors_and_logs_never_contain_the_secret(boot, monkeypatch, caplog):
    """The lifespan pins carvis.main at INFO, so this covers what is actually emitted."""
    monkeypatch.setenv("CARVIS_ENV", "prod")
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)
    with caplog.at_level("DEBUG"), pytest.raises(WebhookConfigurationError) as exc:
        boot()
    assert SECRET not in str(exc.value)
    assert SECRET not in caplog.text
    monkeypatch.setenv("CARVIS_ENV", "production")
    with caplog.at_level("DEBUG"):
        boot()
    assert SECRET not in caplog.text
