"""Port: storing, fetching and deleting bytes by key.

Spec: /architecture/media-storage.md, /decisions/adr-0010-media-retention.md

Nothing in this product stored a byte before visual intake, and this port exists to keep that
break narrow: one capability, two adapters, chosen by configuration in `composition/`.

It deliberately does **not** list and does **not** sign URLs. Both would invite the access
pattern the spec is trying to prevent - media is read through one authorised, tenant-checked
endpoint, and there is no path a browser can guess (MS-05).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class BlobStoreUnavailable(Exception):
    """The configured backing store cannot be used, named so start-up can fail clearly (MS-01)."""


@runtime_checkable
class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write `data` at `key`, replacing anything already there."""
        ...

    async def get(self, key: str) -> bytes | None:
        """The bytes at `key`, or None when nothing is there - including after retention."""
        ...

    async def delete(self, key: str) -> None:
        """Remove `key`. Deleting something that is already gone is not an error."""
        ...
