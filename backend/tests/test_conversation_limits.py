"""M2 Track A3: call binding cannot be hijacked, call mappings are pruned, and unauthenticated
session creation is throttled and capped without evicting live sessions.

Uses the simulated phone and real Vapi webhook shapes from test_conversation.py. Interim until the
durable, provider-confirmed binding of Track B5.
"""
from __future__ import annotations

import time

import pytest

import conversation
import main
from conversation import (MAX_BOUND_CALLS_PER_SESSION, SESSION_CREATE_WINDOW_SECONDS, SESSION_CREATES_PER_WINDOW,
                          SESSION_TTL_SECONDS, ConversationStore, SessionLimitExceeded)
from tests.test_conversation import SECRET, VEHICLE, Phone, api, client, payload, run, vapi  # noqa: F401  (api is a fixture)

CONFIRM = ("c-confirm", "confirm_vehicle", {"year": "2022", "make": "subaru", "model": "wrx"})
LOOKUP = ("c-lookup", "lookup_spec", {"query": "ride height tolerance"})


class Clock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def store(api, monkeypatch):
    """A fresh store with a controllable throttle clock, installed behind the HTTP API."""
    clock = Clock()
    fresh = ConversationStore(clock=clock)
    fresh.clock = clock
    monkeypatch.setattr(main, "conversations", fresh)
    return fresh


async def bind(http, phone, call_id, generation=None):
    generation = phone.generation if generation is None else generation
    return await http.post(f"/conversation/sessions/{phone.id}/calls/{generation}/bind", headers=phone.auth,
                           json={"vapi_call_id": call_id})


async def create(http, owner="Gabriel Eisenberg", vehicle=None):
    return await http.post("/conversation/sessions", json={"owner_name": owner, "vehicle": vehicle or VEHICLE})


# --- Binding -----------------------------------------------------------------------------------


def test_another_session_cannot_take_over_a_bound_call(store):
    """Previously bind_call overwrote the mapping, so the victim's webhooks reached the attacker."""
    async def scenario():
        async with client() as http:
            victim, attacker = Phone(http), Phone(http)
            await victim.start()
            await attacker.start()
            await victim.call(vapi_call_id="vapi-victim")
            await attacker.call(vapi_call_id=None)
            refused = await bind(http, attacker, "vapi-victim")
            assert refused.status_code == 409
            assert refused.json() == {"detail": "stale call"}
            [entry] = await vapi(http, CONFIRM, call_id="vapi-victim")
            assert payload(entry)["status"] == "confirmed"
            return victim.id, await victim.state(), await attacker.state()
    victim_id, victim_state, attacker_state = run(scenario())
    assert victim_state["vehicle_confirmed"] is True
    assert attacker_state["vehicle_confirmed"] is False
    assert store._calls["vapi-victim"][0] == victim_id


def test_attacker_cannot_take_over_by_binding_first_after_the_victim(store):
    """Whoever binds a call ID first keeps it; a later bind from anyone else is refused."""
    async def scenario():
        async with client() as http:
            victim, attacker = Phone(http), Phone(http)
            await victim.start()
            await attacker.start()
            await victim.call(vapi_call_id=None)
            await attacker.call(vapi_call_id=None)
            assert (await bind(http, victim, "vapi-shared")).status_code == 200
            assert (await bind(http, attacker, "vapi-shared")).status_code == 409
            assert (await bind(http, victim, "vapi-shared")).status_code == 200
            return victim.id
    victim_id = run(scenario())
    assert store._calls["vapi-shared"][0] == victim_id


def test_repeating_the_same_binding_is_accepted(store):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id="vapi-1")
            assert (await bind(http, phone, "vapi-1")).status_code == 200
            assert (await bind(http, phone, "vapi-1")).status_code == 200
            return phone.id
    session_id = run(scenario())
    assert store._session_calls[session_id] == ["vapi-1"], "an idempotent re-bind must not duplicate"


def test_webhook_before_bind_then_phone_bind_is_idempotent(store):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id=None)
            [entry] = await vapi(http, CONFIRM, call_id="vapi-early", variables={"carvis_session_id": phone.id})
            assert payload(entry)["status"] == "confirmed"
            assert (await bind(http, phone, "vapi-early")).status_code == 200
            correction = ("c-again", "confirm_vehicle", {"year": "2022", "make": "subaru", "model": "wrx",
                                                         "transmission": "manual"})
            [entry] = await vapi(http, correction, call_id="vapi-early")
            return payload(entry)["status"], await phone.state()
    status, state = run(scenario())
    assert status == "confirmed"
    assert state["call_active"] is True


def test_phone_bind_supersedes_a_different_webhook_auto_bind(store):
    """A webhook that auto-bound some other call ID first must not stay current next to the phone's."""
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id=None)
            [entry] = await vapi(http, CONFIRM, call_id="vapi-intruder", variables={"carvis_session_id": phone.id})
            assert payload(entry)["status"] == "confirmed"  # before the phone binds: B5 removes this path
            assert (await bind(http, phone, "vapi-phone")).status_code == 200
            [entry] = await vapi(http, LOOKUP, call_id="vapi-intruder", variables={"carvis_session_id": phone.id})
            assert payload(entry)["status"] == "stale_call"
            ended = {"message": {"type": "end-of-call-report",
                                 "call": {"id": "vapi-intruder",
                                          "assistantOverrides": {"variableValues": {"carvis_session_id": phone.id}}}}}
            assert (await http.post("/vapi-tool", json=ended, headers={"x-vapi-secret": SECRET})).status_code == 200
            after_intruder_end = await phone.state()
            # The superseded ID can never be bound again, even by the session that saw it.
            assert (await bind(http, phone, "vapi-intruder")).status_code == 409
            [entry] = await vapi(http, LOOKUP, call_id="vapi-phone")
            return after_intruder_end, payload(entry)["status"]
    after_intruder_end, status = run(scenario())
    assert after_intruder_end["call_active"] is True, "a superseded call must not end the current one"
    assert status != "stale_call"


def test_one_generation_has_one_current_call_id(store):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id=None)
            for call_id in ("vapi-a", "vapi-b", "vapi-c"):
                assert (await bind(http, phone, call_id)).status_code == 200
            statuses = []
            for call_id in ("vapi-a", "vapi-b"):
                [entry] = await vapi(http, LOOKUP, call_id=call_id)
                statuses.append(payload(entry)["status"])
            return phone.id, statuses
    session_id, statuses = run(scenario())
    assert statuses == ["stale_call", "stale_call"]
    current = [cid for cid, (sid, gen) in store._calls.items() if sid == session_id and gen != -1]
    assert current == ["vapi-c"]


def test_an_earlier_call_id_cannot_be_rebound_to_a_new_call(store):
    """Re-pointing an old call at the current generation would make its stale webhooks current."""
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id="vapi-old")
            await phone.end()
            await phone.call(vapi_call_id=None)
            assert (await bind(http, phone, "vapi-old")).status_code == 409
            assert (await bind(http, phone, "vapi-new")).status_code == 200
            [entry] = await vapi(http, LOOKUP, call_id="vapi-old")
            return payload(entry)["status"]
    assert run(scenario()) == "stale_call"


def test_stale_generation_bind_is_still_refused(store):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id="vapi-1")
            first = phone.generation
            await phone.end()
            await phone.call(vapi_call_id=None)
            return (await bind(http, phone, "vapi-2", generation=first)).status_code
    assert run(scenario()) == 409


# --- Pruning -----------------------------------------------------------------------------------


def test_call_mappings_per_session_are_capped(store):
    """An authenticated client looping binds with fresh IDs cannot grow _calls without bound."""
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id=None)
            for n in range(MAX_BOUND_CALLS_PER_SESSION * 4):
                assert (await bind(http, phone, f"vapi-loop-{n}")).status_code == 200
            return phone
    phone = run(scenario())
    assert len(store._calls) == MAX_BOUND_CALLS_PER_SESSION
    assert len(store._session_calls[phone.id]) == MAX_BOUND_CALLS_PER_SESSION
    assert "vapi-loop-0" not in store._calls
    newest = f"vapi-loop-{MAX_BOUND_CALLS_PER_SESSION * 4 - 1}"
    assert [cid for cid, (_, gen) in store._calls.items() if gen != -1] == [newest]


def test_a_pruned_call_id_is_stale_not_current(store):
    """Even after its mapping is pruned, an old call cannot act on the session's current call."""
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id="vapi-first")
            for n in range(MAX_BOUND_CALLS_PER_SESSION):
                await phone.end()
                await phone.call(vapi_call_id=f"vapi-later-{n}")
            assert "vapi-first" not in store._calls
            [entry] = await vapi(http, CONFIRM, call_id="vapi-first", variables={"carvis_session_id": phone.id})
            assert payload(entry)["status"] == "stale_call"
            return await phone.state()
    assert run(scenario())["vehicle_confirmed"] is False


def test_unknown_call_id_cannot_act_on_a_bound_session(store):
    """An echoed carvis_session_id with some other call ID does not reach the bound current call."""
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id="vapi-real")
            [entry] = await vapi(http, CONFIRM, call_id="vapi-forged", variables={"carvis_session_id": phone.id})
            assert payload(entry)["status"] == "stale_call"
            return await phone.state()
    assert run(scenario())["vehicle_confirmed"] is False
    assert "vapi-forged" not in store._calls


def test_expired_sessions_release_their_call_mappings(store):
    async def scenario():
        async with client() as http:
            old, new = Phone(http), Phone(http)
            await old.start()
            await old.call(vapi_call_id="vapi-recycled")
            store._sessions[old.id].last_seen = time.monotonic() - SESSION_TTL_SECONDS - 1
            await new.start()  # creation runs expiry
            assert old.id not in store._sessions
            assert "vapi-recycled" not in store._calls and old.id not in store._session_calls
            await new.call(vapi_call_id=None)
            assert (await bind(http, new, "vapi-recycled")).status_code == 200
            return new.id
    new_id = run(scenario())
    assert store._calls["vapi-recycled"][0] == new_id


# --- Session creation limits -------------------------------------------------------------------


def test_creation_is_throttled_with_retry_after(store):
    async def scenario():
        async with client() as http:
            for _ in range(SESSION_CREATES_PER_WINDOW):
                assert (await create(http)).status_code == 200
            store.clock.now += 10
            return await create(http)
    response = run(scenario())
    assert response.status_code == 429
    assert response.json() == {"detail": "Too many conversation sessions. Try again later."}
    assert response.headers["retry-after"] == str(int(SESSION_CREATE_WINDOW_SECONDS - 10))
    assert len(store._sessions) == SESSION_CREATES_PER_WINDOW


def test_throttle_window_slides(store):
    async def scenario():
        async with client() as http:
            for _ in range(SESSION_CREATES_PER_WINDOW):
                assert (await create(http)).status_code == 200
            assert (await create(http)).status_code == 429
            store.clock.now += SESSION_CREATE_WINDOW_SECONDS
            return await create(http)
    assert run(scenario()).status_code == 200


def test_refused_and_invalid_requests_do_not_consume_the_budget(store):
    async def scenario():
        async with client() as http:
            for _ in range(5):
                assert (await create(http, vehicle={"year": "22", "make": "x", "model": "y"})).status_code == 400
                assert (await http.post("/conversation/sessions", json={})).status_code == 422
            for _ in range(SESSION_CREATES_PER_WINDOW):
                assert (await create(http)).status_code == 200
            for _ in range(5):
                assert (await create(http)).status_code == 429
            store.clock.now += SESSION_CREATE_WINDOW_SECONDS
            return await create(http)
    assert run(scenario()).status_code == 200


def test_full_store_refuses_instead_of_evicting_live_sessions(store, monkeypatch):
    """Previously a flood evicted the least-recently-seen session, ending a mechanic's live call."""
    monkeypatch.setattr(conversation, "MAX_SESSIONS", 3)

    async def scenario():
        async with client() as http:
            live = Phone(http)
            await live.start()
            await live.call(vapi_call_id="vapi-live")
            store._sessions[live.id].last_seen = time.monotonic() - 60
            for _ in range(2):
                assert (await create(http, owner="Flood")).status_code == 200
            refused = await create(http, owner="Flood")
            state = await live.state()
            [entry] = await vapi(http, CONFIRM, call_id="vapi-live")
            return refused, state, payload(entry)["status"]
    refused, state, status = run(scenario())
    assert refused.status_code == 429
    retry_after = int(refused.headers["retry-after"])
    assert SESSION_TTL_SECONDS - 120 <= retry_after <= SESSION_TTL_SECONDS
    assert state["call_active"] is True, "the live session must survive"
    assert status == "confirmed"
    assert len(store._sessions) == 3


def test_expired_sessions_free_capacity(store, monkeypatch):
    monkeypatch.setattr(conversation, "MAX_SESSIONS", 2)

    async def scenario():
        async with client() as http:
            assert (await create(http)).status_code == 200
            assert (await create(http)).status_code == 200
            assert (await create(http)).status_code == 429
            for session in store._sessions.values():
                session.last_seen = time.monotonic() - SESSION_TTL_SECONDS - 1
            return await create(http)
    assert run(scenario()).status_code == 200
    assert len(store._sessions) == 1


def test_successful_creation_response_is_unchanged(store):
    async def scenario():
        async with client() as http:
            return await create(http)
    response = run(scenario())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"session_id", "device_token", "state"}
    assert body["state"]["vehicle_confirmed"] is False


def test_limit_error_carries_a_positive_retry_after():
    assert SessionLimitExceeded("throttled", 0).retry_after == 1
    assert SessionLimitExceeded("full", -5).retry_after == 1
    assert SessionLimitExceeded("full", 30).retry_after == 30


def test_documented_interim_limits():
    assert (SESSION_CREATES_PER_WINDOW, SESSION_CREATE_WINDOW_SECONDS) == (20, 60.0)
    assert MAX_BOUND_CALLS_PER_SESSION == 16
    assert conversation.MAX_SESSIONS == 256
