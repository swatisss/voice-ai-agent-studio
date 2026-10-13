"""Storing and expiring captured frames.

Spec: /architecture/media-storage.md, /decisions/adr-0010-media-retention.md

Bounds on the way in, a clock on every object, and no URL anyone can hold. Retention deletes the
bytes and leaves the row, so a case stays readable after its images are gone (MS-04, DM-06).
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.blobstore import blob_store
from voiceai.core.config import get_settings
from voiceai.core.db import new_id, utcnow
from voiceai.modules.evidence import repo
from voiceai.modules.evidence.domain import EncodedFrame
from voiceai.core.tables import MediaObject

log = logging.getLogger("voiceai.media")


def store_key(tenant_id: str, call_id: str) -> str:
    """Keys are generated, never derived from a request, and never guessable."""
    return f"{tenant_id}/{call_id}/{new_id()}.jpg"


async def store_frame(
    session: AsyncSession, *, tenant_id: str, call_id: str, frame: EncodedFrame, source: str
) -> MediaObject:
    """Write the bytes and record the row. The caller has already applied the bounds."""
    key = store_key(tenant_id, call_id)
    await blob_store().put(key, frame.data, frame.content_type)
    return await repo.add_media(
        session, tenant_id=tenant_id, call_id=call_id, store_key=key,
        content_type=frame.content_type, size=len(frame.data), width=frame.width,
        height=frame.height, source=source,
    )


async def read_frame(session: AsyncSession, tenant_id: str, media_id: str) -> tuple[bytes, str] | None:
    """The bytes of one object, for the one authorised endpoint (MS-05).

    Another tenant's id, an unknown id and an object retention has removed are all the same answer
    to the caller: nothing.
    """
    row = await repo.media_for(session, tenant_id, media_id)
    if row is None or row.deleted_at is not None:
        return None
    data = await blob_store().get(row.store_key)
    if data is None:
        return None
    return data, row.content_type


async def prune_expired(session: AsyncSession, tenant_id: str) -> int:
    """Delete this tenant's objects past the retention window; leave their evidence rows (MS-04)."""
    days = get_settings().media_retention_days
    rows = await repo.expired_media(session, tenant_id, repo.retention_cutoff(days))
    store = blob_store()
    for row in rows:
        try:
            await store.delete(row.store_key)
        except Exception as exc:  # noqa: BLE001 - a key we cannot delete must not stall retention
            log.warning("could not delete media %s (%s): %s", row.id, row.store_key, exc)
            continue
        row.deleted_at = utcnow()
    if rows:
        await session.flush()
        log.info("retention removed %d media object(s) older than %d days", len(rows), days)
    return len(rows)
