"""The configured blob store, behind the BlobStore port.

Spec: /architecture/media-storage.md, /decisions/adr-0010-media-retention.md

`local` by default; `gcs` when configuration says so. Only this accessor and `composition/` know
which adapter is in use - the evidence module names the capability and never the backing store
(/architecture/modular-structure.md).
"""
from __future__ import annotations

from voiceai.core.config import get_settings
from voiceai.ports.blobstore import BlobStore, BlobStoreUnavailable

__all__ = ["BlobStore", "BlobStoreUnavailable", "blob_store", "reset_blob_store"]

_store: BlobStore | None = None


def blob_store() -> BlobStore:
    global _store
    if _store is None:
        settings = get_settings()
        backend = (settings.media_backend or "local").strip().lower()
        if backend == "gcs":
            from voiceai.adapters.blobstore.gcs import build

            _store = build(settings.media_bucket)
        elif backend == "local":
            from voiceai.adapters.blobstore.local import build

            _store = build(settings.media_dir)
        else:
            raise BlobStoreUnavailable(f"unknown MEDIA_BACKEND {backend!r}; use 'local' or 'gcs'")
    return _store


def reset_blob_store() -> None:
    global _store
    _store = None
