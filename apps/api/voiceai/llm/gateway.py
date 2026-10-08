"""LLM gateway: roles -> provider models, over a pluggable wire adapter.

Spec: /architecture/llm-gateway.md, /decisions/adr-0003-llm-gateway.md

This module owns routing policy and nothing about any single provider: role -> model ref
resolution, the fallback chain, per-model request params, prices, usage estimation, the one
corrective JSON retry, and the fake responder used by tests. The HTTP conversation belongs to a
wire adapter in `voiceai/adapters/llm/`, chosen by the `wire:` key of a `providers:` entry
(/architecture/llm-gateway.md, "Adding a provider").
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from voiceai.adapters.llm.registry import DEFAULT_WIRE, UnknownWire, client_for
from voiceai.config import get_settings
from voiceai.ports.llm import BadRequest, ChatClient, ChatResult, ProviderConfig, Retryable, ToolCall, Usage

log = logging.getLogger("voiceai.llm")
T = TypeVar("T", bound=BaseModel)

ROLES = ("realtime", "analysis", "drafting", "simulator", "judge", "turn")

__all__ = [
    "ROLES", "ChatResult", "FakeReply", "Gateway", "LLMError", "LLMJsonError", "ToolCall", "Usage",
    "fake_active", "gateway", "reset_gateway", "set_fake",
]


class LLMError(Exception):
    """Raised when every model ref for a role failed."""


class LLMJsonError(LLMError):
    """Raised when JSON output fails validation after the retry."""


# A wire adapter signals "try the next ref" with ports.llm.Retryable; the old private name is
# kept because it is the gateway's documented fallback trigger.
_Retryable = Retryable


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
        settings = get_settings()
        for role in self.roles:  # LG-06/LG-07: real env var wins, then apps/api/.env
            env = os.environ.get(f"LLM_ROLE_{role.upper()}") or getattr(settings, f"llm_role_{role}", None)
            if env:
                self.roles[role]["model"] = env
        self._clients: dict[str, ChatClient] = {}

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

    def api_key(self, provider: str) -> str | None:
        """The provider's key, from its declared `api_key_env` variable or the .env line of the
        same name. No provider is named in code (LG-12)."""
        p = self.providers.get(provider)
        return get_settings().env_value(p["api_key_env"]) if p else None

    def provider_configured(self, provider: str) -> bool:
        return bool(self.api_key(provider))

    def _provider_cfg(self, provider: str) -> ProviderConfig:
        p = self.providers[provider]
        key = self.api_key(provider)
        if not key:
            raise Retryable(f"{p['api_key_env']} not set")
        options = {"stream_usage": p.get("stream_usage", False), **(p.get("options") or {})}
        return ProviderConfig(
            name=provider, wire=p.get("wire", DEFAULT_WIRE), base_url=p["base_url"], api_key=key,
            headers=p.get("headers") or {}, options=options,
        )

    def _client(self, provider: str) -> ChatClient:
        if provider in self._clients:
            return self._clients[provider]
        if provider not in self.providers:
            raise Retryable(f"unknown provider {provider}")
        try:
            client = client_for(self._provider_cfg(provider))
        except UnknownWire as exc:  # LG-14: an unusable wire is skipped like a missing key
            raise Retryable(str(exc)) from exc
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
        result = ChatResult(model_ref=ref)
        async for ev in client.stream(model, messages, tools, self._params(role, ref)):
            if ev["type"] == "text":
                yield ev
            else:
                result = ev["result"]
                result.model_ref = ref
        if not result.usage.input_tokens:  # the provider reported none: estimate from characters
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
        json_schema = schema.model_json_schema()
        msgs = [
            {"role": "system", "content": f"Respond with a single JSON object that matches this JSON Schema:\n{json.dumps(json_schema)}"},
            *messages,
        ]
        use_schema = bool(self.models.get(ref, {}).get("json_schema"))
        total = Usage()
        last_error = ""
        for _attempt in range(2):  # LG-04: one retry with the validation error
            try:
                content, usage = await client.complete_json(
                    model, msgs, json_schema if use_schema else None, self._params(role, ref)
                )
            except BadRequest as exc:
                if use_schema:
                    use_schema = False  # provider rejected json_schema: retry same model with json_object
                    continue
                raise LLMJsonError(str(exc)) from exc
            total.input_tokens += usage.input_tokens
            total.output_tokens += usage.output_tokens
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
