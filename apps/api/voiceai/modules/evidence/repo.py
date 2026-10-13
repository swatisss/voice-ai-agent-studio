"""Row access for media objects, pinned evidence and cases.

Spec: /architecture/visual-intake.md, /data/data-model.md

Every helper takes `tenant_id` as a required argument, and single rows go through `get_owned`, so
another tenant's id is indistinguishable from a missing one (VI-13, MT-05).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_owned, utcnow
from voiceai.core.tables import CallEvidence, MediaObject, VisualCase


# ---------------------------------------------------------------- media
async def add_media(
    session: AsyncSession, *, tenant_id: str, call_id: str, store_key: str, content_type: str,
    size: int, width: int, height: int, source: str,
) -> MediaObject:
    row = MediaObject(
        tenant_id=tenant_id, call_id=call_id, kind="frame", store_key=store_key,
        content_type=content_type, bytes=size, width=width, height=height, source=source,
    )
    session.add(row)
    await session.flush()
    return row


async def media_for(session: AsyncSession, tenant_id: str, media_id: str) -> MediaObject | None:
    return await get_owned(session, MediaObject, tenant_id, media_id)


async def frames_stored(session: AsyncSession, tenant_id: str, call_id: str) -> int:
    """How many frames this call has stored, including ones retention has since removed.

    Counting the rows rather than the live objects is deliberate: the per-call cap is about how
    much the agent looked, not about what is still on disk (MS-03).
    """
    return int(
        await session.scalar(
            select(func.count())
            .select_from(MediaObject)
            .where(MediaObject.tenant_id == tenant_id, MediaObject.call_id == call_id)
        )
        or 0
    )


async def expired_media(
    session: AsyncSession, tenant_id: str, older_than: datetime, limit: int = 500
) -> list[MediaObject]:
    """Objects past the retention window whose bytes have not been deleted yet.

    Tenant-scoped like everything else: the retention job is queued per tenant and prunes only
    that tenant's media, so nothing here is the one query that reads across tenants.
    """
    return list(
        (
            await session.scalars(
                select(MediaObject)
                .where(
                    MediaObject.tenant_id == tenant_id,
                    MediaObject.deleted_at.is_(None),
                    MediaObject.created_at < older_than,
                )
                .limit(limit)
            )
        ).all()
    )


def retention_cutoff(days: int) -> datetime:
    return utcnow() - timedelta(days=days)


# ---------------------------------------------------------------- evidence
async def add_evidence(
    session: AsyncSession, *, tenant_id: str, call_id: str, media_id: str | None, source: str,
    description: str, items: list[dict], confidence: str, safety_flag: str, asked_for: str,
    caller_words: str,
) -> CallEvidence:
    seq = await next_seq(session, tenant_id, call_id)
    row = CallEvidence(
        tenant_id=tenant_id, call_id=call_id, seq=seq, media_id=media_id, source=source,
        description=description, items=items, confidence=confidence, safety_flag=safety_flag,
        asked_for=asked_for or None, caller_words=caller_words,
    )
    session.add(row)
    await session.flush()
    return row


async def next_seq(session: AsyncSession, tenant_id: str, call_id: str) -> int:
    highest = await session.scalar(
        select(func.max(CallEvidence.seq)).where(
            CallEvidence.tenant_id == tenant_id, CallEvidence.call_id == call_id
        )
    )
    return int(highest or 0) + 1


async def evidence_for(session: AsyncSession, tenant_id: str, call_id: str) -> list[CallEvidence]:
    return list(
        (
            await session.scalars(
                select(CallEvidence)
                .where(CallEvidence.tenant_id == tenant_id, CallEvidence.call_id == call_id)
                .order_by(CallEvidence.seq)
            )
        ).all()
    )


# ---------------------------------------------------------------- cases
async def case_for(session: AsyncSession, tenant_id: str, call_id: str) -> VisualCase | None:
    return await session.scalar(
        select(VisualCase).where(VisualCase.tenant_id == tenant_id, VisualCase.call_id == call_id)
    )


async def open_case(
    session: AsyncSession, *, tenant_id: str, call_id: str, agent_id: str, kind: str
) -> VisualCase:
    """Open the call's case, or return the one it already has (VI-08)."""
    existing = await case_for(session, tenant_id, call_id)
    if existing:
        return existing
    row = VisualCase(tenant_id=tenant_id, call_id=call_id, agent_id=agent_id, kind=kind)
    session.add(row)
    await session.flush()
    return row
