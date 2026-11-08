"""Hands-free conversation: real Vapi webhook shapes, a simulated phone, and real local Qdrant.

Vapi's payloads follow its published SDK types: message.toolCallList[].function.arguments is a
serialized string, and message.call carries the call ID and assistantOverrides.variableValues.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from qdrant_client import QdrantClient

import conversation
import main
from qdrant_v2 import configure, upsert_records
from tests.test_ride_height import COLLECTION, Embeddings, records

SECRET = "test-only"
JPEG = b"\xff\xd8\xff\xe0demo-photo"
VEHICLE = {"year": "2022", "make": "Subaru", "model": "WRX"}
VISUAL = {"component": "front strut", "confidence": 0.8, "visual_context": "Coil spring over a damper.", "uncertainty": "partly hidden"}


@pytest.fixture
def api(monkeypatch):
    db = QdrantClient(":memory:")
    configure(db, COLLECTION)
    upsert_records(db, Embeddings(), records(), COLLECTION)
    monkeypatch.setattr(main, "COLLECTION_NAME", COLLECTION)
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(main, "conversations", conversation.ConversationStore())
    identify = AsyncMock(return_value=dict(VISUAL))
    monkeypatch.setattr(main, "identify_component", identify)
    main.app.state.qdrant = db
    main.app.state.embedder = Embeddings()
    yield identify
    db.close()


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://carvis", timeout=30)


class Phone:
    """What the iPhone does, over the same HTTP API."""

    def __init__(self, http):
        self.http = http

    async def start(self, **vehicle):
        response = await self.http.post("/conversation/sessions", json={"owner_name": "Gabriel Eisenberg", "vehicle": {**VEHICLE, **vehicle}})
        assert response.status_code == 200, response.text
        body = response.json()
        self.id, self.auth = body["session_id"], {"Authorization": f"Bearer {body['device_token']}"}
        return body

    async def call(self, opening_question=None, vapi_call_id="vapi-1"):
        response = await self.http.post(f"/conversation/sessions/{self.id}/calls", headers=self.auth, json={"opening_question": opening_question})
        assert response.status_code == 200, response.text
        self.generation = response.json()["generation"]
        self.variables = response.json()["variable_values"]
        if vapi_call_id:
            bound = await self.http.post(f"/conversation/sessions/{self.id}/calls/{self.generation}/bind", headers=self.auth, json={"vapi_call_id": vapi_call_id})
            assert bound.status_code == 200
        return response.json()

    async def next_command(self, wait=2):
        response = await self.http.get(f"/conversation/sessions/{self.id}/camera/next", params={"wait": wait}, headers=self.auth)
        return None if response.status_code == 204 else response.json()

    async def photo(self, request_id, data=JPEG):
        return await self.http.post(f"/conversation/sessions/{self.id}/camera/{request_id}/photo", headers=self.auth,
                                    files={"file": ("glasses.jpg", data, "image/jpeg")})

    async def end(self, reason="app"):
        return await self.http.post(f"/conversation/sessions/{self.id}/calls/{self.generation}/end", headers=self.auth, json={"reason": reason})

    async def state(self):
        return (await self.http.get(f"/conversation/sessions/{self.id}", headers=self.auth)).json()


def webhook(*calls, call_id="vapi-1", variables=None):
    tool_calls = [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}} for cid, name, args in calls]
    return {"message": {"type": "tool-calls", "toolCallList": tool_calls, "timestamp": 1,
                        "toolWithToolCallList": [{"type": "function", "toolCall": t} for t in tool_calls],
                        "call": {"id": call_id, "assistantOverrides": {"variableValues": variables or {}}}}}


async def vapi(http, *calls, **kw):
    response = await http.post("/vapi-tool", json=webhook(*calls, **kw), headers={"x-vapi-secret": SECRET})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def payload(entry):
    return json.loads(entry["result"])


async def confirmed(http, **vehicle):
    phone = Phone(http)
    await phone.start(**vehicle)
    await phone.call()
    await vapi(http, ("c0", "confirm_vehicle", {"year": "2022", "make": "subaru", "model": "wrx"}))
    return phone


def run(coro):
    return asyncio.run(coro)


def test_session_requires_its_own_token(api):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            assert (await http.get(f"/conversation/sessions/{phone.id}")).status_code == 401
            bad = {"Authorization": "Bearer nope"}
            assert (await http.get(f"/conversation/sessions/{phone.id}", headers=bad)).status_code == 401
            other = Phone(http)
            await other.start()
            assert (await http.get(f"/conversation/sessions/{phone.id}", headers=other.auth)).status_code == 401
    run(scenario())


def test_webhook_requires_the_vapi_secret(api):
    async def scenario():
        async with client() as http:
            assert (await http.post("/vapi-tool", json=webhook(("c", "lookup_spec", {})))).status_code == 401
    run(scenario())


def test_call_variables_carry_the_profile_and_no_specifications(api):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call()
            assert phone.variables["owner_first_name"] == "Gabriel"
            assert phone.variables["vehicle_summary"] == "2022 Subaru WRX"
            assert phone.variables["vehicle_model"] == "WRX"
            assert phone.variables["vehicle_confirmed"] == "no"
            assert phone.variables["carvis_session_id"] == phone.id
    run(scenario())


def test_no_specification_before_the_vehicle_is_confirmed_aloud(api):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call()
            [entry] = await vapi(http, ("c1", "lookup_spec", {"query": "ride height tolerance"}))
            assert payload(entry)["status"] == "vehicle_unconfirmed"
            assert "message" not in entry
            assert (await phone.state())["pending_question"] == "ride height tolerance"
    run(scenario())


def test_grounded_answer_is_spoken_verbatim_and_remembered(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            [entry] = await vapi(http, ("c1", "lookup_spec", {"query": "what is the ride height tolerance"}))
            body = payload(entry)
            assert entry["name"] == "lookup_spec" and entry["toolCallId"] == "c1"
            assert body["status"] == "answered" and body["source_grounded"] is True
            assert entry["message"] == {"type": "request-complete", "role": "assistant", "content": body["answer"]}
            assert "plus 24 millimeters, minus 12 millimeters" in entry["message"]["content"]
            state = await phone.state()
            assert state["component"] == "suspension_height" and state["spec_type"] == "tolerance"
            assert state["grounded_answer"]["sources"][0]["source_page"] == 14
            assert state["pending_question"] is None
    run(scenario())


def test_refusal_is_for_the_model_to_word_and_has_no_scripted_speech(api):
    async def scenario():
        async with client() as http:
            await confirmed(http)
            [entry] = await vapi(http, ("c1", "lookup_spec", {"query": "what is the rear ride height"}))
            assert payload(entry)["status"] == "clarification"
            assert "message" not in entry
    run(scenario())


def test_model_supplied_vehicle_cannot_override_memory(api):
    async def scenario():
        async with client() as http:
            await confirmed(http)
            [entry] = await vapi(http, ("c1", "lookup_spec", {"query": "ride height tolerance", "make": "ford", "model": "f150", "year": "2021"}))
            assert payload(entry)["status"] == "vehicle_conflict"
            assert "message" not in entry
    run(scenario())


def test_confirmed_variants_are_used_for_lookup(api):
    async def scenario():
        async with client() as http:
            await confirmed(http)
            await vapi(http, ("c1", "confirm_vehicle", {"wheel_size": "18 inch"}))
            [entry] = await vapi(http, ("c2", "lookup_spec", {"query": "rear ride height"}))
            assert "minus 9 millimeters" in entry["message"]["content"]
    run(scenario())


def test_several_tools_in_one_turn_keep_their_own_results(api):
    async def scenario():
        async with client() as http:
            await confirmed(http)
            results = await vapi(http, ("a", "lookup_spec", {"query": "ride height tolerance"}),
                                 ("b", "set_work_context", {"operation": "inspection"}),
                                 ("c", "lookup_spec", {"query": "front ride height on the 17 inch model"}))
            assert [r["toolCallId"] for r in results] == ["a", "b", "c"]
            assert "plus 24" in results[0]["message"]["content"]
            assert "message" not in results[1]
            assert "133 millimeters" in results[2]["message"]["content"]
    run(scenario())


def test_spoken_vehicle_correction_invalidates_dependent_memory(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            await vapi(http, ("c1", "lookup_spec", {"query": "ride height tolerance"}))
            [entry] = await vapi(http, ("c2", "confirm_vehicle", {"year": "2023", "make": "subaru", "model": "wrx"}))
            assert payload(entry)["changed"] == ["year"]
            state = await phone.state()
            assert state["vehicle"]["year"] == "2023" and state["vehicle_confirmed"] is True
            assert state["component"] is None and state["grounded_answer"] is None
    run(scenario())


def test_adding_a_missing_detail_keeps_what_was_already_established(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            await vapi(http, ("c1", "lookup_spec", {"query": "ride height tolerance"}))
            await vapi(http, ("c2", "confirm_vehicle", {"wheel_size": "18-inch"}))
            state = await phone.state()
            assert state["vehicle"]["wheel_size"] == "18-inch"
            assert state["grounded_answer"] is not None
    run(scenario())


def test_changing_a_confirmed_detail_invalidates_what_depended_on_it(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http, wheel_size="18-inch")
            await vapi(http, ("c1", "lookup_spec", {"query": "rear ride height"}))
            await vapi(http, ("c2", "confirm_vehicle", {"wheel_size": "17-inch"}))
            state = await phone.state()
            assert state["vehicle"]["wheel_size"] == "17-inch"
            assert state["grounded_answer"] is None and state["component"] is None
    run(scenario())


def test_spoken_answers_do_not_repeat_the_vehicle(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http, wheel_size="18-inch")
            reply = await vapi(http, ("c1", "lookup_spec", {"query": "rear ride height"}))
            spoken = reply[0]["message"]["content"]
            assert "subaru" not in spoken.lower() and "wrx" not in spoken.lower() and "2022" not in spoken
            assert "minus 9 millimeters" in spoken
            assert (await phone.state())["grounded_answer"]["text"] == spoken
    run(scenario())


def test_correcting_the_part_invalidates_the_previous_answer(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            await vapi(http, ("c1", "lookup_spec", {"query": "ride height tolerance"}))
            await vapi(http, ("c2", "set_work_context", {"component": "camber fastener"}))
            state = await phone.state()
            assert state["component"] == "camber_fastener" and state["grounded_answer"] is None
    run(scenario())


def test_memory_survives_across_calls_in_a_session(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            await vapi(http, ("c1", "lookup_spec", {"query": "ride height tolerance"}))
            await phone.end()
            await phone.call(vapi_call_id="vapi-2")
            assert phone.variables["vehicle_confirmed"] == "yes"
            assert "suspension height" in phone.variables["memory_summary"]
            # The summary tells the model an answer exists without carrying its numbers.
            assert "24" not in phone.variables["memory_summary"]
    run(scenario())


def test_opening_question_is_not_repeated_in_the_prompt_variables(api):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(opening_question="how much can the ride height be off")
            assert "how much can the ride height be off" not in phone.variables["memory_summary"]
            assert (await phone.state())["pending_question"] == "how much can the ride height be off"
    run(scenario())


def test_look_at_part_resolves_the_original_waiting_tool_call(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this part"})))
            command = await phone.next_command()
            assert command["question"] == "what is this part" and command["generation"] == phone.generation
            assert not waiting.done()
            uploaded = await phone.photo(command["request_id"])
            assert uploaded.status_code == 200, uploaded.text
            [entry] = await waiting
            assert entry["toolCallId"] == "look-1"
            body = payload(entry)
            assert body["status"] == "identified" and body["visual_hypothesis"]["component"] == "front strut"
            assert "message" not in entry
            assert api.await_count == 1
            year, make, model = api.await_args.args[2:5]
            assert (year, make, model) == ("2022", "subaru", "wrx")
    run(scenario())


def test_camera_needs_a_confirmed_vehicle(api):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call()
            [entry] = await vapi(http, ("look-1", "look_at_part", {"question": "what is this"}))
            assert payload(entry)["status"] == "vehicle_unconfirmed"
            assert await phone.next_command(wait=0) is None
    run(scenario())


def test_a_retried_webhook_joins_the_same_camera_request(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            first = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            command = await phone.next_command()
            second = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            await asyncio.sleep(0.05)
            assert await phone.next_command(wait=0) is None
            assert (await phone.photo(command["request_id"])).status_code == 200
            assert payload((await first)[0]) == payload((await second)[0])
            assert api.await_count == 1
    run(scenario())


def test_duplicate_and_unknown_photos_are_refused(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            command = await phone.next_command()
            assert (await phone.photo("not-a-request")).status_code == 409
            assert (await phone.photo(command["request_id"])).status_code == 200
            await waiting
            assert (await phone.photo(command["request_id"])).status_code == 409
            assert api.await_count == 1
    run(scenario())


def test_a_photo_from_an_earlier_call_is_refused(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            command = await phone.next_command()
            await phone.end()
            assert payload((await waiting)[0])["status"] == "camera_cancelled"
            await phone.call(vapi_call_id="vapi-2")
            assert (await phone.photo(command["request_id"])).status_code == 409
            assert api.await_count == 0
    run(scenario())


def test_vapi_end_of_call_cancels_the_waiting_tool(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            await phone.next_command()
            event = {"message": {"type": "end-of-call-report", "call": {"id": "vapi-1"}}}
            assert (await http.post("/vapi-tool", json=event, headers={"x-vapi-secret": SECRET})).status_code == 200
            assert payload((await waiting)[0])["status"] == "camera_cancelled"
            assert (await phone.state())["call_active"] is False
    run(scenario())


def test_a_tool_call_from_an_ended_call_is_refused(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            await phone.end()
            await phone.call(vapi_call_id="vapi-2")
            [entry] = await vapi(http, ("c9", "lookup_spec", {"query": "ride height tolerance"}), call_id="vapi-1")
            assert payload(entry)["status"] == "stale_call"
    run(scenario())


def test_camera_deadline_returns_and_later_photo_is_stale(api, monkeypatch):
    monkeypatch.setattr(conversation, "CAMERA_DEADLINE_SECONDS", 0.1)
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            command = await phone.next_command()
            result = (await waiting)[0]
            assert payload(result)["status"] == "camera_timeout"
            assert (await phone.photo(command["request_id"])).status_code == 409
    run(scenario())


def test_phone_can_report_that_it_could_not_take_a_photo(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            command = await phone.next_command()
            response = await http.post(f"/conversation/sessions/{phone.id}/camera/{command['request_id']}/failure",
                                       headers=phone.auth, json={"reason": "stream paused"})
            assert response.status_code == 200
            body = payload((await waiting)[0])
            assert body["status"] == "camera_unavailable" and body["reason"] == "stream paused"
    run(scenario())


def test_vision_guesses_at_measurements_never_reach_the_conversation(api):
    api.return_value = {"component": "strut", "confidence": 0.5, "uncertainty": "unclear",
                        "visual_context": "A coil spring. Probably 133 mm tall. Painted black."}
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            waiting = asyncio.create_task(vapi(http, ("look-1", "look_at_part", {"question": "what is this"})))
            await phone.photo((await phone.next_command())["request_id"])
            visual = payload((await waiting)[0])["visual_hypothesis"]
            assert visual["visual_context"] == "A coil spring. Painted black."
    run(scenario())


def test_webhook_can_arrive_before_the_phone_binds_the_call(api):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            await phone.call(vapi_call_id=None)
            [entry] = await vapi(http, ("c1", "confirm_vehicle", {"year": "2022", "make": "subaru", "model": "wrx"}),
                                 call_id="vapi-early", variables={"carvis_session_id": phone.id})
            assert payload(entry)["status"] == "confirmed"
            assert (await phone.state())["vehicle_confirmed"] is True
    run(scenario())


def test_editing_the_vehicle_in_the_app_requires_confirming_it_again(api):
    async def scenario():
        async with client() as http:
            phone = await confirmed(http)
            response = await http.put(f"/conversation/sessions/{phone.id}/vehicle", headers=phone.auth,
                                      json={"year": "2021", "make": "subaru", "model": "wrx"})
            assert response.status_code == 200
            assert response.json()["vehicle_confirmed"] is False
    run(scenario())


def test_legacy_lookup_without_a_session_keeps_working(api):
    async def scenario():
        async with client() as http:
            payload_ = {"message": {"toolCallList": [{"id": "x", "function": {"name": "lookup_spec", "arguments": json.dumps(
                {"query": "ride height tolerance", "year": "2022", "make": "subaru", "model": "wrx", "shop_id": "shop_demo"})}}]}}
            response = await http.post("/vapi-tool", json=payload_, headers={"x-vapi-secret": SECRET})
            assert response.json()["results"][0]["source_grounded"] is True
    run(scenario())
