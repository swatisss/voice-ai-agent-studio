"""Wire registry: a `wire:` key in models.yaml resolves to an adapter module.

Spec: /architecture/llm-gateway.md (Adding a provider)

Adding a provider that speaks a wire we already have: one `providers:` entry plus its API key
environment variable. Adding a new wire: one module in this package, named after the wire,
exposing `build(cfg) -> ChatClient`. Neither touches the gateway, the routes or the settings.
"""
from __future__ import annotations

import re
from importlib import import_module

from voiceai.ports.llm import ChatClient, ClientFactory, ProviderConfig

DEFAULT_WIRE = "openai"
ALIASES = {"openai": "openai_compatible"}  # friendlier models.yaml spellings
_WIRE_RE = re.compile(r"[a-z][a-z0-9_]{1,30}")


class UnknownWire(Exception):
    """No adapter module for this wire. The gateway treats it like a missing API key (LG-14)."""


def factory(wire: str) -> ClientFactory:
    if not _WIRE_RE.fullmatch(wire):  # models.yaml must not be able to name an arbitrary module
        raise UnknownWire(f"invalid wire name {wire!r}")
    name = f"voiceai.adapters.llm.{ALIASES.get(wire, wire)}"
    try:
        module = import_module(name)  # lazily, so an unused provider's SDK is never imported
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("voiceai.adapters.llm"):
            raise UnknownWire(f"wire {wire!r} needs {exc.name}, which is not installed") from exc
        raise UnknownWire(f"no adapter for wire {wire!r} (expected {name})") from exc
    build = getattr(module, "build", None)
    if build is None:
        raise UnknownWire(f"{name} has no build(cfg) factory")
    return build


def client_for(cfg: ProviderConfig) -> ChatClient:
    return factory(cfg.wire)(cfg)
