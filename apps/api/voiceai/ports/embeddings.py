"""Port: turning text into vectors.

Spec: /architecture/knowledge.md (Embeddings), /decisions/adr-0004-storage-and-vectors.md

`embed` is called off the event loop, so an implementation may block. It MUST return L2-normalised
rows of width `DIM` in the order it was given them, and MUST be deterministic for the same input,
because stored chunk vectors and query vectors are compared directly: changing provider requires
`voiceai reindex`. `name` identifies the provider in logs and reindex decisions.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

import numpy as np

DIM = 384
Kind = Literal["passage", "query"]


@runtime_checkable
class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str], kind: Kind = "passage") -> np.ndarray:
        """One L2-normalised row per text, shape (len(texts), DIM). May block."""
        ...


def normalize(mat: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation, leaving all-zero rows alone. Shared by every adapter."""
    norms = np.linalg.norm(mat, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms
