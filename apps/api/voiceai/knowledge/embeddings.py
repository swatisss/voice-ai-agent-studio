"""Text embeddings: local fastembed (default) or a deterministic hash embedder.

Spec: /architecture/knowledge.md (Embeddings), /decisions/adr-0004-storage-and-vectors.md
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from typing import Literal

import numpy as np

from voiceai.config import get_settings

DIM = 384
Kind = Literal["passage", "query"]
_STOP = set(
    "a an the and or of to in on for with is are was were be been it this that my me i you your we our "
    "do does did can could would should how what when where which who why at by from as about into".split()
)


def normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class HashEmbedder:
    """Hashed bag of words + bigrams. Deterministic, offline, low quality (tests)."""

    name = "hash"

    def embed(self, texts: list[str], kind: Kind = "passage") -> np.ndarray:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]
            feats = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                out[row, h % DIM] += 1.0 if (h >> 8) % 2 == 0 else -1.0
        return normalize(out)


class FastEmbedder:
    name = "fastembed"
    model_name = "BAAI/bge-small-en-v1.5"

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def _load(self):  # noqa: ANN202
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                cache = get_settings().fastembed_cache
                cache.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(model_name=self.model_name, cache_dir=str(cache))
        return self._model

    def embed(self, texts: list[str], kind: Kind = "passage") -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        model = self._load()
        vectors = model.query_embed(texts) if kind == "query" else model.passage_embed(texts)
        return normalize(np.array(list(vectors), dtype=np.float32))


_embedder: HashEmbedder | FastEmbedder | None = None


def embedder() -> HashEmbedder | FastEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = FastEmbedder() if get_settings().embeddings_provider == "fastembed" else HashEmbedder()
    return _embedder


def reset_embedder() -> None:
    global _embedder
    _embedder = None


async def embed(texts: list[str], kind: Kind = "passage") -> np.ndarray:
    """Embed off the event loop (CPU-bound)."""
    return await asyncio.to_thread(embedder().embed, texts, kind)


async def embed_one(text: str, kind: Kind = "passage") -> list[float]:
    return (await embed([text], kind))[0].tolist()
