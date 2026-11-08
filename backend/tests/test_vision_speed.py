"""Identifying a part happens during a live call, so it has to answer quickly."""
import asyncio
import json
from types import SimpleNamespace

import main


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        reply = json.dumps({"component": "alternator", "confidence": 0.9, "visual_context": "pulley and fan", "uncertainty": ""})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def test_nemotron_identifies_without_slow_reasoning(monkeypatch):
    fake = FakeCompletions()
    monkeypatch.setattr(main, "VISION_PROVIDER", "nemotron")
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    monkeypatch.setattr(main, "_VISION_CLIENT", SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    result = asyncio.run(main.identify_component(b"\xff\xd8\xff", "what is this", "2022", "subaru", "wrx"))
    assert result["component"] == "alternator"
    assert fake.kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
