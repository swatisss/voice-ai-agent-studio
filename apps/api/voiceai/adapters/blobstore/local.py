"""Adapter: the blob-store port backed by a directory on the local filesystem.

Spec: /architecture/media-storage.md

The default, and correct for one instance. It is wrong for two - a local directory stops being
shared state and starts being a bug - which is the same constraint ADR-0005 already places on the
process-local session registry, and is why the horizontal-scaling CP has this on its list.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from voiceai.ports.blobstore import BlobStoreUnavailable

log = logging.getLogger("voiceai.media")


def build(root: str | Path) -> LocalBlobStore:
    return LocalBlobStore(Path(root))


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - a read-only data path
            raise BlobStoreUnavailable(f"cannot create media directory {self.root}: {exc}") from exc

    def _path(self, key: str) -> Path:
        # Keys are generated internally, never taken from a request, but a key that escaped the
        # root would be the one bug in this file that mattered, so it is checked rather than
        # trusted.
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise BlobStoreUnavailable(f"refusing a media key outside the store: {key}")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)

        def _read() -> bytes | None:
            return path.read_bytes() if path.is_file() else None

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def _unlink() -> None:
            path.unlink(missing_ok=True)

        await asyncio.to_thread(_unlink)
