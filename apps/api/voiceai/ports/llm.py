"""Port: the wire one LLM provider speaks, and the result shapes the gateway works in.

Spec: /architecture/llm-gateway.md, /decisions/adr-0003-llm-gateway.md

A wire adapter knows how to talk to one family of HTTP APIs. It knows nothing about roles,
fallback chains, prices, retries or the fake responder - those stay in the gateway, so adding a
provider never touches routing policy. Adapters live in `voiceai/adapters/llm/<wire>.py` and
expose `build(cfg) -> ChatClient`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str

    def parsed(self) -> dict[str, Any] | None:
        import json

        try:
            value = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0  # adapters leave this at 0.0; only the gateway knows prices


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Usage = field(default_factory=Usage)
    model_ref: str = ""
    first_token_ms: int | None = None


@dataclass(frozen=True)
class ProviderConfig:
    """One `providers:` entry of models.yaml, with the API key already resolved."""

    name: str  # "groq"
    wire: str  # "openai" -> voiceai/adapters/llm/openai_compatible.py
    base_url: str
    api_key: str
    headers: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)  # wire-specific; opaque to the gateway


def text_part(text: str) -> dict[str, Any]:
    """A text part of a multi-part message content."""
    return {"type": "text", "text": text}


def image_part(mime: str, data: str) -> dict[str, Any]:
    """An image part of a multi-part message content: base64 `data`, provider-neutral.

    A message's `content` may be a string or a list of these parts. The wire adapter maps them
    onto whatever the provider wants (the `openai` wire sends a `data:` URI). Only a model whose
    `models.yaml` entry declares `vision: true` is asked to read one (/architecture/llm-gateway.md).
    """
    return {"type": "image", "mime": mime, "data": data}


def redact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages with image payloads replaced by their size, safe to log (LG-17).

    Image bytes are caller content and must never reach a log line, so anything that logs a
    request body goes through this.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            out.append(m)
            continue
        parts: list[Any] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image":
                parts.append({"type": "image", "mime": part.get("mime"), "bytes": len(part.get("data") or "")})
            else:
                parts.append(part)
        out.append({**m, "content": parts})
    return out


def text_of(content: Any) -> str:
    """The text of a message content, string or multi-part, ignoring images.

    The gateway estimates usage from character counts; counting base64 would inflate it wildly.
    """
    if isinstance(content, list):
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return str(content or "")


class Retryable(Exception):
    """Try the next model ref: connection error, timeout, HTTP 429 or 5xx (LG-01)."""


class BadRequest(Exception):
    """A 400-class rejection. The gateway never falls back on this (LG-02), but it may downgrade
    the requested response format once and retry the same model."""


@runtime_checkable
class ChatClient(Protocol):
    """One provider's wire protocol."""

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        params: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield `{"type":"text","text":...}` deltas, then exactly one `{"type":"done","result":ChatResult}`.

        MUST raise `Retryable` for connection errors, timeouts, 429 and 5xx, and `BadRequest` for
        400-class errors; anything else propagates. MUST fill `ChatResult.usage` token counts when
        the provider reports them and leave them at 0 when it does not, so the gateway can
        estimate. MUST NOT set `cost_usd` or `model_ref`.
        """
        ...

    async def complete_json(
        self,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None,  # None asks for a bare JSON object
        params: dict[str, Any],
    ) -> tuple[str, Usage]:
        """Return the raw response text and its usage. Parsing, validation and the one corrective
        retry (LG-04) stay in the gateway."""
        ...


class ClientFactory(Protocol):
    def __call__(self, cfg: ProviderConfig) -> ChatClient: ...
