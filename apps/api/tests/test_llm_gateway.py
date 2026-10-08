"""LLM gateway. Covers: LG-01, LG-02, LG-03, LG-04, LG-05, LG-06, LG-07, LG-08, LG-09, LG-10, LG-11"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from voiceai.adapters.llm import openai_compatible as wire
from voiceai.config import Settings
from voiceai.llm import gateway as gw


@pytest.fixture
def real_mode(monkeypatch):  # noqa: ANN001, ANN201
    """A gateway on the models.yaml chain, deaf to the developer's own .env role overrides."""
    monkeypatch.setattr(gw, "fake_active", lambda: False)
    monkeypatch.setattr(gw, "get_settings", lambda: _settings())
    for role in ROLE_REFS:
        monkeypatch.delenv(f"LLM_ROLE_{role.upper()}", raising=False)
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
    sent: list[list[dict]] = []

    class Client:  # a wire adapter that answers invalid JSON first, then valid JSON
        async def complete_json(self, model, messages, schema, params):  # noqa: ANN001, ANN201
            sent.append(messages)
            return ('{"value": "nope"}' if len(sent) == 1 else '{"value": 7}'), gw.Usage(5, 2)

    monkeypatch.setattr(gw.Gateway, "_client", lambda self, provider: Client())
    out, usage = await real_mode.complete_json("analysis", [{"role": "user", "content": "x"}], Out)
    assert out.value == 7 and len(sent) == 2
    assert (usage.input_tokens, usage.output_tokens) == (10, 4)  # both attempts are billed
    assert "That JSON was invalid" in sent[1][-1]["content"]  # the error is fed back (LG-04)


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


# ---------------------------------------------------------------- OpenAI provider (CP-0008)
ROLE_REFS = ("realtime", "analysis", "drafting", "simulator", "judge", "turn")
STREAM_ROLES = ("realtime", "simulator", "turn")
JSON_ROLES = ("analysis", "drafting", "judge")


def _settings(**keys: str) -> Settings:
    return Settings(_env_file=None, **keys)  # never read the developer's real apps/api/.env


class FakeOpenAI:
    """Stands in for openai.AsyncOpenAI: records requests, can answer 429 for Groq, never touches the network."""

    created: list = []
    groq_limited = False

    def __init__(self, *, base_url: str, api_key: str, default_headers=None, max_retries: int = 0) -> None:  # noqa: ANN001
        self.base_url, self.api_key, self.requests = base_url, api_key, []
        self.chat = SimpleNamespace(completions=self)
        FakeOpenAI.created.append(self)

    async def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.requests.append(kwargs)
        if FakeOpenAI.groq_limited and "groq" in self.base_url:
            request = httpx.Request("POST", self.base_url)
            raise openai.RateLimitError("429 tokens per minute", response=httpx.Response(429, request=request), body=None)
        if kwargs.get("stream"):
            return _Stream()
        message = SimpleNamespace(content='{"value": 1}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3))


class _Stream:
    def __init__(self) -> None:
        text = SimpleNamespace(usage=None, model_extra=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello", tool_calls=None), finish_reason=None)])
        done = SimpleNamespace(usage={"prompt_tokens": 1_000, "completion_tokens": 100}, model_extra=None, choices=[])
        self._chunks = iter([text, done])

    def __aiter__(self):  # noqa: ANN204
        return self

    async def __anext__(self):  # noqa: ANN204
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None


@pytest.fixture
def fake_openai(monkeypatch):  # noqa: ANN001, ANN201
    FakeOpenAI.created, FakeOpenAI.groq_limited = [], False
    monkeypatch.setattr(wire.openai, "AsyncOpenAI", FakeOpenAI)
    monkeypatch.setattr(gw, "fake_active", lambda: False)
    for role in ROLE_REFS:
        monkeypatch.delenv(f"LLM_ROLE_{role.upper()}", raising=False)
    return FakeOpenAI


def _gateway(monkeypatch, **keys: str) -> gw.Gateway:  # noqa: ANN001
    monkeypatch.setattr(gw, "get_settings", lambda: _settings(**keys))
    return gw.Gateway()


async def test_openai_key_from_dotenv_settings_and_healthz(client, monkeypatch, fake_openai):
    """Covers: LG-08"""
    g = _gateway(monkeypatch, openai_api_key="sk-from-dotenv")
    assert g.provider_configured("openai") and not g.provider_configured("groq")
    c = g._client("openai")
    assert c.client.api_key == "sk-from-dotenv" and c.client.base_url == "https://api.openai.com/v1"
    monkeypatch.setattr(gw, "_gateway", g)
    providers = (await client.get("/healthz")).json()["providers"]
    assert providers == {**{n: n == "openai" for n in g.providers}, "deepgram": False}

    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-environment")  # the environment variable wins over the .env line
    assert _gateway(monkeypatch, openai_api_key="sk-from-dotenv")._client("openai").client.api_key == "sk-from-environment"

    monkeypatch.setenv("OPENAI_API_KEY", "")  # neither: the provider is unconfigured and skipped
    none = _gateway(monkeypatch)
    assert not none.provider_configured("openai")
    with pytest.raises(gw._Retryable, match="OPENAI_API_KEY not set"):
        none._client("openai")
    monkeypatch.setattr(gw, "_gateway", none)
    assert (await client.get("/healthz")).json()["providers"]["openai"] is False


async def test_openai_role_request_shape_and_cost(monkeypatch, fake_openai):
    """Covers: LG-09"""
    monkeypatch.setenv("LLM_ROLE_REALTIME", "openai:gpt-4.1-mini")
    g = _gateway(monkeypatch, openai_api_key="sk-test")
    assert g.role_model("realtime") == "openai:gpt-4.1-mini"
    events = [e async for e in g.stream_chat("realtime", [{"role": "user", "content": "hi"}])]
    request = fake_openai.created[-1].requests[0]
    assert request["model"] == "gpt-4.1-mini" and request["stream"] is True
    assert request["stream_options"] == {"include_usage": True} and "reasoning_effort" not in request
    assert request["temperature"] == 0.3 and request["max_tokens"] == 800
    assert fake_openai.created[-1].base_url == "https://api.openai.com/v1"
    result = events[-1]["result"]
    assert result.model_ref == "openai:gpt-4.1-mini" and (result.usage.input_tokens, result.usage.output_tokens) == (1_000, 100)
    assert result.usage.cost_usd == pytest.approx(1_000 * 0.40 / 1e6 + 100 * 1.60 / 1e6)
    assert g.usage_cost("openai:gpt-4.1-mini", gw.Usage(1_000_000, 1_000_000)) == pytest.approx(2.00)


async def test_every_role_falls_back_to_openai(monkeypatch, fake_openai):
    """Covers: LG-10"""
    g = _gateway(monkeypatch, openai_api_key="sk-test")  # no Groq or OpenRouter key, no LLM_ROLE_* line
    assert all(g.refs_for(role)[-1].startswith("openai:") for role in ROLE_REFS)
    messages = [{"role": "user", "content": "x"}]
    for role in STREAM_ROLES:
        events = [e async for e in g.stream_chat(role, messages)]
        assert events[-1]["result"].model_ref.startswith("openai:"), role
    for role in JSON_ROLES:
        out, _ = await g.complete_json(role, messages, Out)
        assert out.value == 1
    assert {c.base_url for c in fake_openai.created} == {"https://api.openai.com/v1"}  # Groq and OpenRouter were skipped, not called


async def test_groq_429_is_served_by_openai(monkeypatch, fake_openai):
    """Covers: LG-10"""
    fake_openai.groq_limited = True
    g = _gateway(monkeypatch, groq_api_key="gsk-test", openai_api_key="sk-test")  # no OpenRouter key
    events = [e async for e in g.stream_chat("realtime", [{"role": "user", "content": "x"}])]
    assert events[-1]["result"].model_ref == "openai:gpt-4.1-mini"
    assert [c.base_url for c in fake_openai.created] == ["https://api.groq.com/openai/v1", "https://api.openai.com/v1"]


async def test_openai_models_are_priced_and_selectable(client, monkeypatch, fake_openai):
    """Covers: LG-11"""
    g = _gateway(monkeypatch)
    used = {ref for role in ROLE_REFS for ref in g.refs_for(role) if ref.startswith("openai:")}
    assert used == {"openai:gpt-4.1-mini", "openai:gpt-4.1-nano"}
    assert all(g.models[ref].get("input") and g.models[ref].get("output") for ref in used)
    assert not any(g.models[ref].get("reasoning_effort") for ref in used)  # non-reasoning models only
    monkeypatch.setattr(gw, "_gateway", g)
    selectable = (await client.get("/api/models")).json()["selectable"]
    assert {"openai:gpt-4.1-mini", "openai:gpt-4.1-nano"} <= set(selectable)
