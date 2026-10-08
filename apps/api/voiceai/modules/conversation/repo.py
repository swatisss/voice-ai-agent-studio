"""Row access for calls. Every query here filters by tenant.

Spec: /api/rest-api.md (Calls), /architecture/multi-tenancy.md

Child rows are filtered on their own `tenant_id` rather than only on the call they belong to, so a
mistake above this layer cannot leak another tenant's events (MT-05).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_owned
from voiceai.core.tables import AgentVersion, Call, CallAnalysis, CallEvent, CallFeedback

EXPLORER_LIMIT = 500


@dataclass(frozen=True)
class CallFilter:
    agent_id: str | None = None
    outcome: str | None = None
    channel: str | None = None
    direction: str | None = None
    feedback: str | None = None  # a rating, or "none" for calls nobody rated (FB-05)
    include_seed: bool = True


@dataclass(frozen=True)
class CallDetail:
    call: Call
    analysis: CallAnalysis | None
    version: int | None
    feedback: CallFeedback | None
    events: list[CallEvent]


def _apply(q: Select, f: CallFilter) -> Select:
    for column, value in ((Call.agent_id, f.agent_id), (Call.outcome, f.outcome),
                          (Call.channel, f.channel), (Call.direction, f.direction)):
        if value:
            q = q.where(column == value)
    if f.feedback == "none":  # FB-05
        q = q.where(CallFeedback.rating.is_(None))
    elif f.feedback:
        q = q.where(CallFeedback.rating == f.feedback)
    if not f.include_seed:
        q = q.where(Call.is_seed.is_(False))
    return q


async def explorer_rows(s: AsyncSession, tenant_id: str, f: CallFilter) -> list[tuple[Any, ...]]:
    """Calls for the explorer, newest first: (call, analysis, version number, rating)."""
    q = (
        select(Call, CallAnalysis, AgentVersion.version, CallFeedback.rating)
        .outerjoin(CallAnalysis, CallAnalysis.call_id == Call.id)
        .outerjoin(CallFeedback, CallFeedback.call_id == Call.id)
        .outerjoin(AgentVersion, AgentVersion.id == Call.agent_version_id)
        .where(Call.tenant_id == tenant_id, Call.is_eval.is_(False))  # API-04
        .order_by(Call.started_at.desc())
        .limit(EXPLORER_LIMIT)
    )
    return list((await s.execute(_apply(q, f))).all())


async def detail(s: AsyncSession, tenant_id: str, call_id: str) -> CallDetail | None:
    """Everything the call-detail page shows, or None when this tenant does not own the call."""
    call = await get_owned(s, Call, tenant_id, call_id)
    if call is None:
        return None
    version = await s.get(AgentVersion, call.agent_version_id) if call.agent_version_id else None
    return CallDetail(
        call=call,
        analysis=await s.scalar(
            select(CallAnalysis).where(CallAnalysis.call_id == call_id, CallAnalysis.tenant_id == tenant_id)
        ),
        version=version.version if version else None,
        feedback=await s.scalar(
            select(CallFeedback).where(CallFeedback.call_id == call_id, CallFeedback.tenant_id == tenant_id)
        ),
        events=list((await s.scalars(
            select(CallEvent)
            .where(CallEvent.call_id == call_id, CallEvent.tenant_id == tenant_id)
            .order_by(CallEvent.seq)
        )).all()),
    )
