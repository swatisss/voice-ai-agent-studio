"""The vision role: image parts reach the wire, and a model that cannot read one is skipped.

Covers: LG-16, LG-17
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from voiceai.adapters.llm import openai_compatible as wire
from voiceai.core.config import Settings
from voiceai.core.llm import gateway as gw
from voiceai.ports.llm import Usage, image_part, redact, text_of, text_part

ROLES = ("realtime", "analysis", "drafting", "simulator", "judge", "turn", "vision")
JPEG = base64.b64encode(b"\xff\xd8\xff" + b"synthetic-frame-bytes" * 8).decode()


class Observation(BaseModel):
    description: str
    confidence: str


def _config(tmp_path: Path, *, vision_capable: bool) -> Path:
    """A models.yaml whose vision chain is, or is not, able to read an image."""
    path = tmp_path / "models.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "providers": {"openai": {"wire": "openai", "base_url": "https://api.openai.test/v1", "api_key_env": "OPENAI_API_KEY"}},
                "models": {"openai:seeing": {"input": 1.0, "output": 2.0, "json_schema": True, "vision": vision_capable}},
                "roles": {"vision": {"model": "openai:seeing", "params": {"temperature": 0}}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _gateway(monkeypatch, config: Path, **keys: str) -> gw.Gateway:  # noqa: ANN001
    monkeypatch.setattr(gw, "fake_active", lambda: False)
    monkeypatch.setattr(gw, "get_settings", lambda: Settings(_env_file=None, **keys))
    for role in ROLES:
        monkeypatch.delenv(f"LLM_ROLE_{role.upper()}", raising=False)
    return gw.Gateway(config)


@pytest.fixture
def captured(monkeypatch):  # noqa: ANN001, ANN201
    """Stub the OpenAI client so the request this wire would send can be inspected offline."""
    sent: list[dict] = []

    class Completions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN202
            sent.append(kwargs)

            class Message:
                content = '{"description": "A bed side rail is bent.", "confidence": "confirmed"}'

            class Choice:
                message = Message()

            class Usage_:
                prompt_tokens = 1_000_000
                completion_tokens = 1_000_000

            class Response:
                choices = [Choice()]
                usage = Usage_()

            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(wire.openai, "AsyncOpenAI", lambda **_kw: Client())
    return sent


async def test_image_part_reaches_the_wire(monkeypatch, tmp_path, captured):  # noqa: ANN001
    """Covers: LG-16"""
    g = _gateway(monkeypatch, _config(tmp_path, vision_capable=True), openai_api_key="sk-test")
    assert g.role_available("vision") is True

    messages = [{"role": "user", "content": [text_part("What is visible?"), image_part("image/jpeg", JPEG)]}]
    obs, usage = await g.complete_json("vision", messages, Observation)

    assert obs.confidence == "confirmed"
    # the image became a data URI on this wire, and the text part came through beside it
    parts = captured[-1]["messages"][-1]["content"]
    assert {p["type"] for p in parts} == {"text", "image_url"}
    assert parts[1]["image_url"]["url"] == f"data:image/jpeg;base64,{JPEG}"
    assert parts[0]["text"] == "What is visible?"
    # priced from the table like any other role: 1M in at 1.0 + 1M out at 2.0
    assert usage.cost_usd == pytest.approx(3.0)


async def test_a_model_that_cannot_see_is_skipped(monkeypatch, tmp_path, captured):  # noqa: ANN001
    """Covers: LG-16"""
    g = _gateway(monkeypatch, _config(tmp_path, vision_capable=False), openai_api_key="sk-test")

    assert g.refs_for("vision") == []          # the only ref lacks the capability
    assert g.role_available("vision") is False  # so video degrades to voice (VI-01)

    with pytest.raises(gw.LLMError):
        await g.complete_json("vision", [{"role": "user", "content": [image_part("image/jpeg", JPEG)]}], Observation)
    assert captured == []  # and nothing was sent


async def test_missing_key_makes_the_role_unavailable(monkeypatch, tmp_path):  # noqa: ANN001
    """Covers: LG-16"""
    g = _gateway(monkeypatch, _config(tmp_path, vision_capable=True))
    assert g.refs_for("vision") == ["openai:seeing"]  # capable, but unusable
    assert g.role_available("vision") is False


async def test_image_bytes_never_reach_a_log_line(monkeypatch, tmp_path, captured, caplog):  # noqa: ANN001
    """Covers: LG-17"""
    g = _gateway(monkeypatch, _config(tmp_path, vision_capable=True), openai_api_key="sk-test")
    messages = [{"role": "user", "content": [text_part("look"), image_part("image/jpeg", JPEG)]}]

    with caplog.at_level(logging.DEBUG, logger="voiceai.llm.wire"):
        await g.complete_json("vision", messages, Observation)

    assert caplog.text, "the wire should debug-log its request"
    assert JPEG not in caplog.text
    assert "look" in caplog.text  # the prompt text is still useful to see
    assert "image/jpeg" in caplog.text


def test_redaction_and_text_extraction_helpers() -> None:
    """Covers: LG-17"""
    messages = [
        {"role": "system", "content": "a string content is untouched"},
        {"role": "user", "content": [text_part("hello"), image_part("image/png", JPEG)]},
    ]
    safe = redact(messages)
    assert safe[0] == messages[0]
    assert safe[1]["content"][1] == {"type": "image", "mime": "image/png", "bytes": len(JPEG)}
    assert JPEG not in str(safe)
    # usage estimation counts the words, not the payload
    assert text_of(messages[1]["content"]) == "hello"
    assert text_of("plain") == "plain"


def test_usage_estimate_ignores_image_payloads(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """Covers: LG-16"""
    g = _gateway(monkeypatch, _config(tmp_path, vision_capable=True), openai_api_key="sk-test")
    big = [{"role": "user", "content": [text_part("four"), image_part("image/jpeg", JPEG)]}]
    estimated = sum(len(text_of(m.get("content"))) for m in big) // 4
    assert estimated == 1  # "four" / 4, not thousands of base64 characters
    assert g.usage_cost("openai:seeing", Usage(1_000_000, 0)) == pytest.approx(1.0)
