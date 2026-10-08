"""Adapter: a deterministic hashed bag-of-words embedder. Offline, instant, low quality.

Spec: /architecture/knowledge.md (Embeddings)

Used by the test suite and by anyone working without the model cache. Good enough to rank an
exact-ish phrase match, not good enough for paraphrase, which is why its score thresholds differ
from fastembed's (/architecture/knowledge.md, Search).
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

from voiceai.ports.embeddings import DIM, Kind, normalize

_STOP = set(
    "a an the and or of to in on for with is are was were be been it this that my me i you your we our "
    "do does did can could would should how what when where which who why at by from as about into".split()
)


class HashEmbedder:
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


def build() -> HashEmbedder:
    return HashEmbedder()
