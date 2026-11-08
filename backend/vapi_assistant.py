"""Create or update the Carvis assistant on Vapi from this repo. One prompt, real server tools.

    python backend/vapi_assistant.py --public-url https://YOUR-HOST

Reads VAPI_PRIVATE_KEY and VAPI_WEBHOOK_SECRET from backend/.env. Set VAPI_ASSISTANT_ID to update
an existing assistant; otherwise one is created and its ID printed. --dry-run prints the
configuration with secrets removed and sends nothing.

The prompt owns conversational wording. Code owns routing, state, tools, and evidence.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from conversation import CAMERA_DEADLINE_SECONDS, OPERATIONS, SPEC_TYPES
from spec_extract import COMPONENTS
from spec_schema import VARIANTS

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
PROMPT_PATH = ROOT / "vapi" / "assistant_prompt.md"
API = "https://api.vapi.ai/assistant"
MODEL = "gpt-4.1-mini"
# Vapi must wait longer than the server's own camera deadline, so the server always answers first.
LOOK_TIMEOUT_SECONDS = int(CAMERA_DEADLINE_SECONDS) + 10
LOOKUP_TIMEOUT_SECONDS = 15


def _tool(name: str, description: str, properties: dict, required: list[str], server: dict, timeout: int) -> dict:
    # Without a request-start message, Vapi says stock lines like "Hold on a sec" on every tool call.
    return {"type": "function", "async": False, "messages": [{"type": "request-start", "content": ""}],
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object", "properties": properties, "required": required}},
            "server": {**server, "timeoutSeconds": timeout}}


def tools(server: dict) -> list[dict]:
    text = {"type": "string"}
    return [
        _tool("confirm_vehicle",
              "Record the vehicle after the mechanic confirms or corrects it aloud. Pass only details they actually said.",
              {"year": text, "make": text, "model": text,
               **{variant: {"type": "string", "description": description} for variant, description in (
                   ("transmission", "6MT or CVT"), ("trim", "Trim name as they said it"),
                   ("wheel_size", "Wheel size in inches, for example 17-inch"),
                   ("engine_code", "Engine code"), ("market", "Market or region"))}},
              [], server, LOOKUP_TIMEOUT_SECONDS),
        _tool("set_work_context",
              "Remember which part and job they are working on. Use this when they switch tasks or correct what you had wrong.",
              {"component": text, "operation": text,
               "clear": {"type": "boolean", "description": "True if what you had was wrong and they haven't said what's right"}},
              [], server, LOOKUP_TIMEOUT_SECONDS),
        _tool("lookup_spec",
              "Look up a specification or procedure in the service manual for the confirmed vehicle. The only source of technical values.",
              {"query": {"type": "string", "description": "What the mechanic asked for, in their words"},
               "component": {"type": "string", "enum": sorted(COMPONENTS)},
               "operation": {"type": "string", "enum": list(OPERATIONS)},
               "spec_type": {"type": "string", "enum": list(SPEC_TYPES)}},
              ["query"], server, LOOKUP_TIMEOUT_SECONDS),
        _tool("look_at_part",
              "Take a new photo through the mechanic's glasses and identify what they are looking at.",
              {"question": {"type": "string", "description": "What they asked about what they're looking at"}},
              ["question"], server, LOOK_TIMEOUT_SECONDS),
        {"type": "endCall"},
    ]


def assistant_config(public_url: str, secret: str) -> dict:
    webhook = public_url.rstrip("/") + "/vapi-tool"
    server = {"url": webhook, "headers": {"x-vapi-secret": secret}}
    return {
        "name": "Carvis",
        # No scripted first line: the model writes the greeting from the system prompt.
        "firstMessageMode": "assistant-speaks-first-with-model-generated-message",
        "model": {"provider": "openai", "model": MODEL, "temperature": 0.3,
                  "messages": [{"role": "system", "content": PROMPT_PATH.read_text().strip()}],
                  "tools": tools(server)},
        # ElevenLabs' stock British voice "Daniel", with a British Azure voice if it's unavailable.
        "voice": {"provider": "11labs", "voiceId": "onwK4e9ZLuTAKqWW03F9", "model": "eleven_turbo_v2_5",
                  "fallbackPlan": {"voices": [{"provider": "azure", "voiceId": "en-GB-RyanNeural"}]}},
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en", "keyterm": ["Carvis"]},
        "clientMessages": ["transcript", "speech-update", "status-update", "user-interrupted"],
        "serverMessages": ["tool-calls", "status-update", "end-of-call-report"],
        "server": {**server, "timeoutSeconds": LOOKUP_TIMEOUT_SECONDS},
        # Working in silence is normal; keep the line open but don't leave it open forever.
        "silenceTimeoutSeconds": 300,
        "maxDurationSeconds": 1800,
    }


def redacted(config: dict) -> dict:
    copied = copy.deepcopy(config)
    for holder in [copied["server"], *[t["server"] for t in copied["model"]["tools"] if "server" in t]]:
        holder["headers"] = {"x-vapi-secret": "(from backend/.env)"}
    return copied


def apply(config: dict, private_key: str, assistant_id: str | None) -> dict:
    url = f"{API}/{assistant_id}" if assistant_id else API
    request = urllib.request.Request(url, data=json.dumps(config).encode(), method="PATCH" if assistant_id else "POST",
                                     headers={"Authorization": f"Bearer {private_key}", "Content-Type": "application/json",
                                              # Vapi's firewall answers 403 (error 1010) to Python's default client name.
                                              "User-Agent": "carvis-setup/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Vapi rejected the configuration ({error.code}): {error.read().decode()[:800]}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--public-url", required=True, help="HTTPS address Vapi can reach this backend at")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.public_url.startswith("https://"):
        parser.error("--public-url must be HTTPS")
    secret = (os.getenv("VAPI_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise SystemExit("VAPI_WEBHOOK_SECRET is not set in backend/.env")
    config = assistant_config(args.public_url, secret)
    if args.dry_run:
        print(json.dumps(redacted(config), indent=2))
        return
    private_key = (os.getenv("VAPI_PRIVATE_KEY") or "").strip()
    if not private_key:
        raise SystemExit("VAPI_PRIVATE_KEY is not set in backend/.env")
    assistant_id = (os.getenv("VAPI_ASSISTANT_ID") or "").strip() or None
    result = apply(config, private_key, assistant_id)
    print(f"Carvis assistant {'updated' if assistant_id else 'created'}: {result.get('id')}")


if __name__ == "__main__":
    main()
