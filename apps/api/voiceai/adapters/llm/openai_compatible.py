"""Adapter: the OpenAI chat-completions wire (Groq, OpenRouter, OpenAI, and anything else that
speaks it - vLLM, Together, Fireworks, Azure, Ollama).

Spec: /architecture/llm-gateway.md, /decisions/adr-0003-llm-gateway.md

Everything provider-specific lives here: client construction, the exception mapping the gateway's
fallback chain depends on, streaming assembly, and the per-provider quirks declared under
`options:` in models.yaml. `options` keys:

  stream_usage      ask for usage on the final stream chunk (`stream_options.include_usage`)
  usage_extra_key   a vendor extension holding usage when the standard field is absent
                    (Groq reports it as `x_groq.usage`)
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import openai

from voiceai.ports.llm import BadRequest, ChatResult, ProviderConfig, Retryable, ToolCall, Usage

FIRST_TOKEN_TIMEOUT_S = 8.0
JSON_TIMEOUT_S = 60.0

RETRY_ERRORS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    asyncio.TimeoutError,
)


def build(cfg: ProviderConfig) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(cfg)


class OpenAICompatibleClient:
    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = openai.AsyncOpenAI(
            base_url=cfg.base_url, api_key=cfg.api_key, default_headers=cfg.headers or None, max_retries=0
        )

    # the gateway's fallback chain is driven entirely by which exception comes back out
    def _translate(self, exc: Exception) -> Exception:
        if isinstance(exc, RETRY_ERRORS):
            return Retryable(str(exc) or type(exc).__name__)
        if isinstance(exc, openai.BadRequestError):
            return BadRequest(str(exc))
        if isinstance(exc, openai.APIStatusError) and (exc.status_code >= 500 or exc.status_code == 429):
            return Retryable(str(exc))
        return exc

    def _usage_from(self, chunk: Any) -> Any:
        usage = getattr(chunk, "usage", None)
        extra_key = self.cfg.options.get("usage_extra_key")
        if usage is None and extra_key:  # e.g. Groq's x_groq.usage on the last chunk
            usage = ((getattr(chunk, "model_extra", None) or {}).get(extra_key) or {}).get("usage")
        return usage

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        params: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": True, **params}
        if tools:
            kwargs["tools"] = tools
        if self.cfg.options.get("stream_usage"):
            kwargs["stream_options"] = {"include_usage": True}
        started = time.perf_counter()
        result = ChatResult()
        calls: dict[int, dict[str, str]] = {}
        try:
            stream = await asyncio.wait_for(self.client.chat.completions.create(**kwargs), FIRST_TOKEN_TIMEOUT_S)
            iterator = stream.__aiter__()
            first = True
            while True:
                try:
                    chunk = await (asyncio.wait_for(iterator.__anext__(), FIRST_TOKEN_TIMEOUT_S) if first else iterator.__anext__())
                except StopAsyncIteration:
                    break
                first = False
                usage = self._usage_from(chunk)
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
        except Exception as exc:  # noqa: BLE001 - mapped to the port's contract
            raise self._translate(exc) from exc
        result.tool_calls = [ToolCall(c["id"] or f"call_{i}", c["name"], c["arguments"]) for i, c in sorted(calls.items())]
        if result.tool_calls:
            result.finish_reason = "tool_calls"
        yield {"type": "done", "result": result}

    async def complete_json(
        self,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None,
        params: dict[str, Any],
    ) -> tuple[str, Usage]:
        kwargs: dict[str, Any] = {"model": model, "messages": messages, **params}
        kwargs["response_format"] = (
            {"type": "json_schema", "json_schema": {"name": schema.get("title") or "Out", "schema": schema, "strict": False}}
            if schema
            else {"type": "json_object"}
        )
        try:
            resp = await asyncio.wait_for(self.client.chat.completions.create(**kwargs), JSON_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - mapped to the port's contract
            raise self._translate(exc) from exc
        usage = Usage()
        if resp.usage:
            usage.input_tokens = resp.usage.prompt_tokens or 0
            usage.output_tokens = resp.usage.completion_tokens or 0
        return (resp.choices[0].message.content or "").strip(), usage

    async def aclose(self) -> None:
        await self.client.close()
