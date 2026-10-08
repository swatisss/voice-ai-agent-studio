"""Adapter: local sentence embeddings through fastembed (BAAI/bge-small-en-v1.5).

Spec: /architecture/knowledge.md (Embeddings), /decisions/adr-0004-storage-and-vectors.md

The model is loaded on first use, not at import, so a process that never embeds (the seeder, the
CLI, a worker image) never pays for it. Loading is guarded by a lock because `embed` runs in a
worker thread.
"""
from __future__ import annotations

import threading

import numpy as np

from voiceai.core.config import get_settings
from voiceai.ports.embeddings import DIM, Kind, normalize


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


def build() -> FastEmbedder:
    return FastEmbedder()
