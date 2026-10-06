"""LLM gateway. Covers: LG-01, LG-02, LG-03, LG-04, LG-05, LG-06"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from voiceai.llm import gateway as gw


@pytest.fixture
def real_mode(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(gw, "fake_active", lambda: False)
    return gw.Gateway()


async def test_fallback_on_retryable(real_mode, monkeypatch):
    """Covers: LG-01"""
    tried: list[str] = []

    async def stream_one(self, role, ref, messages, tools):  # noqa: ANN001, ANN202
        tried.append(ref)
        if ref.startswith("groq:"):
            raise gw._Retryable("503 service unavailable")
        yield {"type": "text", "text": "hi"}
        yield {"type": "done", "result": gw.ChatResult(text="hi", model_ref=ref)}

    monkeypatch.setattr(gw.Gateway, "_stream_one", stream_one)
    events = [e async for e in real_mode.stream_chat("realtime", [{"role": "user", "content": "x"}])]
    assert tried == ["groq:openai/gpt-oss-120b", "openrouter:openai/gpt-oss-120b"]
    assert events[-1]["result"].model_ref == "openrouter:openai/gpt-oss-120b"


async def test_no_fallback_on_validation_error(real_mode, monkeypatch):
    """Covers: LG-02"""
    tried: list[str] = []

    class Boom(Exception):
        pass

    async def stream_one(self, role, ref, messages, tools):  # noqa: ANN001, ANN202
        tried.append(ref)
        raise Boom("400 bad request")
        yield  # pragma: no cover

    monkeypatch.setattr(gw.Gateway, "_stream_one", stream_one)
    with pytest.raises(Boom):
        _ = [e async for e in real_mode.stream_chat("realtime", [{"role": "user", "content": "x"}])]
    assert tried == ["groq:openai/gpt-oss-120b"]


def test_agent_override_is_first_ref(real_mode):
    """Covers: LG-03"""
    refs = real_mode.refs_for("realtime", "openrouter:openai/gpt-oss-120b")
    assert refs[0] == "openrouter:openai/gpt-oss-120b"


class Out(BaseModel):
    value: int


async def test_json_retry_once(real_mode, monkeypatch):
    """Covers: LG-04"""
    calls: list[int] = []

    class Resp:
        def __init__(self, content: str) -> None:
            self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
            self.usage = None

    class Completions:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            calls.append(1)
            return Resp('{"value": "nope"}' if len(calls) == 1 else '{"value": 7}')

    client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    monkeypatch.setattr(gw.Gateway, "_client", lambda self, provider: client)
    out, _ = await real_mode.complete_json("analysis", [{"role": "user", "content": "x"}], Out)
    assert out.value == 7 and len(calls) == 2


def test_usage_cost(real_mode):
    """Covers: LG-05"""
    assert real_mode.usage_cost("groq:openai/gpt-oss-120b", gw.Usage(1_000_000, 1_000_000)) == pytest.approx(0.75)


def test_role_env_override(monkeypatch):
    """Covers: LG-06"""
    monkeypatch.setenv("LLM_ROLE_JUDGE", "groq:openai/gpt-oss-20b")
    assert gw.Gateway().role_model("judge") == "groq:openai/gpt-oss-20b"


def test_role_override_from_dotenv_settings(monkeypatch):
    """Covers: LG-07"""
    from voiceai.config import Settings

    monkeypatch.delenv("LLM_ROLE_JUDGE", raising=False)
    monkeypatch.setattr(gw, "get_settings", lambda: Settings(llm_role_judge="openrouter:openai/gpt-oss-20b"))
    assert gw.Gateway().role_model("judge") == "openrouter:openai/gpt-oss-20b"
    monkeypatch.setenv("LLM_ROLE_JUDGE", "groq:openai/gpt-oss-120b")  # the environment variable wins
    assert gw.Gateway().role_model("judge") == "groq:openai/gpt-oss-120b"
