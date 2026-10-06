"""LLM gateway: roles -> Groq/OpenRouter models via one OpenAI-compatible client.

Spec: /architecture/llm-gateway.md, /decisions/adr-0003-llm-gateway.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import openai
import yaml
from pydantic import BaseModel, ValidationError

from voiceai.config import get_settings

log = logging.getLogger("voiceai.llm")
T = TypeVar("T", bound=BaseModel)

ROLES = ("realtime", "analysis", "drafting", "simulator", "judge")
FIRST_TOKEN_TIMEOUT_S = 8.0
JSON_TIMEOUT_S = 60.0


class LLMError(Exception):
    """Raised when every model ref for a role failed."""


class LLMJsonError(LLMError):
    """Raised when JSON output fails validation after the retry."""


class _Retryable(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str

    def parsed(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Usage = field(default_factory=Usage)
    model_ref: str = ""
    first_token_ms: int | None = None


# ---------------------------------------------------------------- fake provider (tests)
@dataclass
class FakeReply:
    text: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # (name, args)


FakeResponder = Callable[[str, list[dict[str, Any]], list[dict[str, Any]] | None], "FakeReply | str | BaseModel | dict"]
_fake: FakeResponder | None = None


def set_fake(responder: FakeResponder | None) -> None:
    """Install a scripted responder: (role, messages, tools) -> FakeReply | str | dict | BaseModel."""
    global _fake
    _fake = responder


def fake_active() -> bool:
    return _fake is not None or get_settings().llm_fake


def _default_fake(role: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> FakeReply:
    return FakeReply(text="This is a placeholder reply from the fake LLM.")


# ---------------------------------------------------------------- config
class Gateway:
    def __init__(self, config_path: os.PathLike[str] | str | None = None) -> None:
        path = config_path or get_settings().models_config
        with open(path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        self.providers: dict[str, dict[str, Any]] = cfg.get("providers", {})
        self.models: dict[str, dict[str, Any]] = cfg.get("models", {})
        self.roles: dict[str, dict[str, Any]] = cfg.get("roles", {})
        for role in ROLES:  # LG-06: env override per role
            env = os.environ.get(f"LLM_ROLE_{role.upper()}")
            if env:
                self.roles.setdefault(role, {})["model"] = env
        self._clients: dict[str, openai.AsyncOpenAI] = {}

    # -- helpers
    def role_model(self, role: str) -> str:
        return self.roles[role]["model"]

    def selectable(self) -> list[str]:
        return list(self.models.keys())

    def refs_for(self, role: str, override: str | None = None) -> list[str]:
        spec = self.roles[role]
        refs = [override or spec["model"], *spec.get("fallback", [])]
        seen: list[str] = []
        for r in refs:
            if r and r not in seen:
                seen.append(r)
        return seen

    def provider_configured(self, provider: str) -> bool:
        p = self.providers.get(provider)
        return bool(p and os.environ.get(p["api_key_env"]) or self._key_from_settings(provider))

    def _key_from_settings(self, provider: str) -> str | None:
        s = get_settings()
        return {"groq": s.groq_api_key, "openrouter": s.openrouter_api_key}.get(provider)

    def _client(self, provider: str) -> openai.AsyncOpenAI:
        if provider in self._clients:
            return self._clients[provider]
        p = self.providers.get(provider)
        if not p:
            raise _Retryable(f"unknown provider {provider}")
        key = os.environ.get(p["api_key_env"]) or self._key_from_settings(provider)
        if not key:
            raise _Retryable(f"{p['api_key_env']} not set")
        client = openai.AsyncOpenAI(
            base_url=p["base_url"], api_key=key, default_headers=p.get("headers") or None, max_retries=0
        )
        self._clients[provider] = client
        return client

    def usage_cost(self, model_ref: str, usage: Usage) -> float:
        price = self.models.get(model_ref)
        if not price:
            log.warning("no price for %s; cost counted as 0", model_ref)
            return 0.0
        return usage.input_tokens * price.get("input", 0) / 1e6 + usage.output_tokens * price.get("output", 0) / 1e6

    def _params(self, role: str, model_ref: str) -> dict[str, Any]:
        params = dict(self.roles[role].get("params", {}))
        if not self.models.get(model_ref, {}).get("reasoning_effort"):
            params.pop("reasoning_effort", None)
        return params

    # -- streaming chat with tools
    async def stream_chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        override: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yields {"type":"text","text":...} deltas then {"type":"done","result":ChatResult}."""
        if fake_active():
            async for ev in self._fake_stream(role, messages, tools):
                yield ev
            return
        errors: list[str] = []
        for ref in self.refs_for(role, override):
            yielded = False
            try:
                async for ev in self._stream_one(role, ref, messages, tools):
                    if ev["type"] == "text":
                        yielded = True
                    yield ev
                return
            except _Retryable as exc:
                if yielded:
                    raise LLMError(f"{ref} failed mid-stream: {exc}") from exc
                errors.append(f"{ref}: {exc}")
                log.warning("LLM %s failed for role %s, trying fallback: %s", ref, role, exc)
        raise LLMError("all models failed: " + "; ".join(errors))

    async def _stream_one(
        self, role: str, ref: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[dict[str, Any]]:
        provider, model = ref.split(":", 1)
        client = self._client(provider)
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": True, **self._params(role, ref)}
        if tools:
            kwargs["tools"] = tools
        if self.providers[provider].get("stream_usage"):
            kwargs["stream_options"] = {"include_usage": True}
        started = time.perf_counter()
        result = ChatResult(model_ref=ref)
        calls: dict[int, dict[str, str]] = {}
        try:
            stream = await asyncio.wait_for(client.chat.completions.create(**kwargs), FIRST_TOKEN_TIMEOUT_S)
            iterator = stream.__aiter__()
            first = True
            while True:
                try:
                    chunk = await (asyncio.wait_for(iterator.__anext__(), FIRST_TOKEN_TIMEOUT_S) if first else iterator.__anext__())
                except StopAsyncIteration:
                    break
                first = False
                usage = getattr(chunk, "usage", None) or (getattr(chunk, "model_extra", None) or {}).get("x_groq", {}).get("usage")
                if usage:
                    u = usage if isinstance(usage, dict) else usage.model_dump()
                    result.usage.input_tokens = int(u.get("prompt_tokens") or 0)
                    result.usage.output_tokens = int(u.get("completion_tokens") or 0)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    if result.first_token_ms is None:
                        result.first_token_ms = int((time.perf_counter() - started) * 1000)
                    result.text += delta.content
                    yield {"type": "text", "text": delta.content}
                for tc in (delta.tool_calls or []) if delta else []:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
                if choice.finish_reason:
                    result.finish_reason = choice.finish_reason
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError, asyncio.TimeoutError) as exc:
            raise _Retryable(str(exc) or type(exc).__name__) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code == 429:
                raise _Retryable(str(exc)) from exc
            raise
        result.tool_calls = [ToolCall(c["id"] or f"call_{i}", c["name"], c["arguments"]) for i, c in sorted(calls.items())]
        if result.tool_calls:
            result.finish_reason = "tool_calls"
        if not result.usage.input_tokens:
            result.usage.input_tokens = sum(len(str(m.get("content") or "")) for m in messages) // 4
            result.usage.output_tokens = (len(result.text) + sum(len(c.arguments) for c in result.tool_calls)) // 4
        result.usage.cost_usd = self.usage_cost(ref, result.usage)
        yield {"type": "done", "result": result}

    async def _fake_stream(
        self, role: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[dict[str, Any]]:
        reply = (_fake or _default_fake)(role, messages, tools)
        if isinstance(reply, str):
            reply = FakeReply(text=reply)
        assert isinstance(reply, FakeReply), "stream_chat fake must return FakeReply or str"
        result = ChatResult(model_ref="fake:fake", first_token_ms=1)
        for word in reply.text.split(" ") if reply.text else []:
            piece = word + " "
            result.text += piece
            yield {"type": "text", "text": piece}
        result.text = result.text.rstrip()
        result.tool_calls = [ToolCall(f"call_{i}", n, json.dumps(a)) for i, (n, a) in enumerate(reply.tool_calls)]
        result.finish_reason = "tool_calls" if result.tool_calls else "stop"
        result.usage = Usage(input_tokens=100, output_tokens=20, cost_usd=self.usage_cost("groq:openai/gpt-oss-120b", Usage(100, 20)))
        yield {"type": "done", "result": result}

    async def chat(self, role: str, messages: list[dict[str, Any]], override: str | None = None) -> ChatResult:
        """Non-streaming convenience (simulator): collects stream_chat."""
        result = ChatResult()
        async for ev in self.stream_chat(role, messages, None, override):
            if ev["type"] == "done":
                result = ev["result"]
        return result

    # -- structured JSON
    async def complete_json(self, role: str, messages: list[dict[str, Any]], schema: type[T]) -> tuple[T, Usage]:
        if fake_active():
            reply = (_fake or _default_fake)(role, messages, None)
            if isinstance(reply, BaseModel):
                return schema.model_validate(reply.model_dump()), Usage()
            if isinstance(reply, dict):
                return schema.model_validate(reply), Usage()
            if isinstance(reply, str):
                return schema.model_validate_json(reply), Usage()
            raise LLMJsonError("fake responder returned an unsupported type for complete_json")
        errors: list[str] = []
        for ref in self.refs_for(role):
            try:
                return await self._json_one(role, ref, messages, schema)
            except _Retryable as exc:
                errors.append(f"{ref}: {exc}")
                log.warning("LLM %s failed for role %s, trying fallback: %s", ref, role, exc)
        raise LLMError("all models failed: " + "; ".join(errors))

    async def _json_one(self, role: str, ref: str, messages: list[dict[str, Any]], schema: type[T]) -> tuple[T, Usage]:
        provider, model = ref.split(":", 1)
        client = self._client(provider)
        schema_json = json.dumps(schema.model_json_schema())
        msgs = [
            {"role": "system", "content": f"Respond with a single JSON object that matches this JSON Schema:\n{schema_json}"},
            *messages,
        ]
        use_schema = bool(self.models.get(ref, {}).get("json_schema"))
        total = Usage()
        last_error = ""
        for attempt in range(2):  # LG-04: one retry with the validation error
            kwargs: dict[str, Any] = {"model": model, "messages": msgs, **self._params(role, ref)}
            kwargs["response_format"] = (
                {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": False}}
                if use_schema
                else {"type": "json_object"}
            )
            try:
                resp = await asyncio.wait_for(client.chat.completions.create(**kwargs), JSON_TIMEOUT_S)
            except openai.BadRequestError as exc:
                if use_schema:
                    use_schema = False  # provider rejected json_schema: retry same model with json_object
                    continue
                raise LLMJsonError(str(exc)) from exc
            except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError, asyncio.TimeoutError) as exc:
                raise _Retryable(str(exc) or type(exc).__name__) from exc
            except openai.APIStatusError as exc:
                if exc.status_code >= 500:
                    raise _Retryable(str(exc)) from exc
                raise
            if resp.usage:
                total.input_tokens += resp.usage.prompt_tokens or 0
                total.output_tokens += resp.usage.completion_tokens or 0
            content = (resp.choices[0].message.content or "").strip()
            try:
                obj = schema.model_validate_json(_strip_fences(content))
                total.cost_usd = self.usage_cost(ref, total)
                return obj, total
            except ValidationError as exc:
                last_error = str(exc)[:1500]
                msgs = [*msgs, {"role": "assistant", "content": content}, {"role": "user", "content": f"That JSON was invalid: {last_error}\nReturn corrected JSON only."}]
        raise LLMJsonError(f"invalid JSON from {ref}: {last_error}")


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


_gateway: Gateway | None = None


def gateway() -> Gateway:
    global _gateway
    if _gateway is None:
        _gateway = Gateway()
    return _gateway


def reset_gateway() -> None:
    global _gateway
    _gateway = None
