"""Choosing the adapter behind each port.

Spec: /architecture/modular-structure.md (Ports and contracts)

These are **factories, not instances**. Building eagerly here would drag pipecat and fastembed
into every process that imports the application - including `voiceai seed` and `voiceai reindex`,
which deliberately avoid them.
"""
from __future__ import annotations

from typing import Any

from voiceai.core.config import get_settings
from voiceai.core.embeddings import embedder
from voiceai.core.events import bus
from voiceai.core.toolcalling import tool_caller
from voiceai.ports.embeddings import Embedder
from voiceai.ports.eventbus import EventBus
from voiceai.ports.toolcaller import ToolCaller


def tool_caller_for(app: Any | None = None) -> ToolCaller:
    """Relative tool URLs run in-process against `app`; absolute ones go over the network."""
    return tool_caller(app)


def event_bus() -> EventBus:
    return bus


def text_embedder() -> Embedder:
    """Chosen by EMBEDDINGS_PROVIDER; the model loads on first use, not here."""
    return embedder()


def provider_health() -> dict[str, bool]:
    """Which external providers have a key, for /healthz. The LLM providers come from
    models.yaml, so adding one adds a key here with no code change (LG-13)."""
    from voiceai.core.llm.gateway import gateway

    g = gateway()
    return {**{name: g.provider_configured(name) for name in g.providers},
            "deepgram": bool(get_settings().deepgram_api_key)}
