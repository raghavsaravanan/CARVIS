"""The assistant's configuration: one prompt, real tools, and no answers written into it."""
from __future__ import annotations

import re

import conversation
import vapi_assistant


def config():
    return vapi_assistant.assistant_config("https://example.test/", "test-secret")


def server_tools(cfg):
    return [t for t in cfg["model"]["tools"] if t["type"] == "function"]


def test_one_system_prompt_and_no_scripted_first_line():
    cfg = config()
    assert [m["role"] for m in cfg["model"]["messages"]] == ["system"]
    assert "firstMessage" not in cfg
    assert cfg["firstMessageMode"] == "assistant-speaks-first-with-model-generated-message"


def test_prompt_contains_no_specification_values_or_vehicles():
    prompt = vapi_assistant.PROMPT_PATH.read_text()
    assert not re.search(r"\d", prompt), "numbers belong in the manual, not the prompt"
    assert not re.search(r"subaru|wrx|camry|toyota", prompt, re.I)


def test_prompt_uses_the_session_variables_the_server_sends():
    prompt = vapi_assistant.PROMPT_PATH.read_text()
    for variable in ("owner_first_name", "vehicle_summary", "vehicle_confirmed", "memory_summary"):
        assert "{{" + variable + "}}" in prompt


def test_every_tool_is_a_real_authenticated_server_tool():
    tools = server_tools(config())
    assert sorted(t["function"]["name"] for t in tools) == ["confirm_vehicle", "look_at_part", "lookup_spec", "set_work_context"]
    for tool in tools:
        assert tool["server"]["url"] == "https://example.test/vapi-tool"
        assert tool["server"]["headers"] == {"x-vapi-secret": "test-secret"}
        assert tool["async"] is False
        assert "messages" not in tool, "no scripted tool speech"


def test_vapi_waits_longer_than_the_server_camera_deadline():
    look = next(t for t in server_tools(config()) if t["function"]["name"] == "look_at_part")
    assert look["server"]["timeoutSeconds"] > conversation.CAMERA_DEADLINE_SECONDS


def test_look_at_part_is_no_longer_a_client_side_tool():
    look = next(t for t in server_tools(config()) if t["function"]["name"] == "look_at_part")
    assert look["server"]["url"].endswith("/vapi-tool")


def test_dry_run_output_hides_the_secret():
    assert "test-secret" not in str(vapi_assistant.redacted(config()))
