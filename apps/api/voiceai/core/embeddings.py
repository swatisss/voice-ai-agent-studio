"""The embedder every module uses, behind the Embedder port.

Spec: /architecture/knowledge.md (Embeddings), /decisions/adr-0004-storage-and-vectors.md

`EMBEDDINGS_PROVIDER` picks the adapter; a third embedder is a new adapter module plus a name in
this table, with no change to ingestion or search.
"""
from __future__ import annotations

import asyncio

import numpy as np

from voiceai.adapters.embeddings import fastembed, hash as hash_embedder
from voiceai.core.config import get_settings
from voiceai.ports.embeddings import DIM, Embedder, Kind, normalize

__all__ = ["DIM", "Embedder", "Kind", "embed", "embed_one", "embedder", "normalize", "reset_embedder"]

ADAPTERS = {"fastembed": fastembed.build, "hash": hash_embedder.build}

_embedder: Embedder | None = None


def embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        name = get_settings().embeddings_provider
        _embedder = ADAPTERS.get(name, hash_embedder.build)()
    return _embedder


def reset_embedder() -> None:
    global _embedder
    _embedder = None


async def embed(texts: list[str], kind: Kind = "passage") -> np.ndarray:
    """Embed off the event loop (CPU-bound)."""
    return await asyncio.to_thread(embedder().embed, texts, kind)


async def embed_one(text: str, kind: Kind = "passage") -> list[float]:
    return (await embed([text], kind))[0].tolist()
