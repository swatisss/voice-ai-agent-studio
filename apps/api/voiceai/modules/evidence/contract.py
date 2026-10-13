"""The evidence module's only public entry point.

Spec: /architecture/visual-intake.md, /architecture/modular-structure.md

Everything a look needs about the call is passed in, so this module names no other module: the
turn loop owns the transcript and the caller's words, and hands them over. That is what keeps the
graph acyclic while `voice` implements the FrameSource port the other way round.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.modules.evidence import repo, service
from voiceai.modules.evidence.service import LookResult, _Context

__all__ = [
    "LookResult", "case_for_call", "case_kind_for", "evidence_for_call", "look_at_camera",
    "open_case", "packet_evidence", "record_ticket", "states_reporting_intent",
]

case_kind_for = service.case_kind_for
states_reporting_intent = service.states_reporting_intent
transcript_of = service.transcript_of


def _context(
    *, tenant_id: str, call_id: str, agent_id: str, case_kind: str, caller_words: str = "",
    asset_hint: str = "", transcript: str = "", caller_verified: bool = False,
    entities: dict[str, Any] | None = None,
) -> _Context:
    return _Context(
        tenant_id=tenant_id, call_id=call_id, agent_id=agent_id, case_kind=case_kind,
        caller_words=caller_words, asset_hint=asset_hint, transcript=transcript,
        caller_verified=caller_verified, entities=entities or {},
    )


async def look_at_camera(session: AsyncSession, **ctx: Any) -> LookResult:
    """Take one frame, describe it, pin it, keep the case current (VI-05, VI-07, VI-08)."""
    return await service.look(session, _context(**ctx))


async def open_case(session: AsyncSession, **ctx: Any) -> dict[str, Any]:
    """Open the call's case because the caller stated the reporting intent (VI-08)."""
    return await service.ensure_case(session, _context(**ctx))


async def case_for_call(session: AsyncSession, tenant_id: str, call_id: str) -> dict[str, Any] | None:
    row = await repo.case_for(session, tenant_id, call_id)
    return service.as_dict(row) if row else None


async def evidence_for_call(session: AsyncSession, tenant_id: str, call_id: str) -> list[dict[str, Any]]:
    """The pinned evidence in order, for call detail and the hand-off packet (VI-07, ES-09)."""
    return [
        {
            "seq": e.seq, "media_id": e.media_id, "source": e.source, "description": e.description,
            "items": list(e.items or []), "confidence": e.confidence, "safety_flag": e.safety_flag,
            "asked_for": e.asked_for or "", "caller_words": e.caller_words,
            "at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in await repo.evidence_for(session, tenant_id, call_id)
    ]


async def packet_evidence(session: AsyncSession, tenant_id: str, call_id: str) -> dict[str, Any] | None:
    """What the groundwork packet carries for a call that looked at something (ES-09).

    Built deterministically from the stored rows rather than drafted, so it survives a fallback
    packet - a safety hand-off is exactly where the LLM packet is least likely to be waited for
    and the human most needs to see what the agent saw.
    """
    entries = await evidence_for_call(session, tenant_id, call_id)
    if not entries:
        return None
    packet: dict[str, Any] = {
        "visual_evidence": [
            {k: e[k] for k in ("media_id", "source", "description", "confidence", "asked_for")}
            for e in entries
        ]
    }
    case = await case_for_call(session, tenant_id, call_id)
    if case:
        packet["visual_case"] = {k: case[k] for k in ("kind", "routing", "routing_reason")}
    return packet


async def record_ticket(session: AsyncSession, tenant_id: str, call_id: str, ticket_ref: str) -> None:
    """Record the reference the business system returned for this call's case (VI-12)."""
    row = await repo.case_for(session, tenant_id, call_id)
    if row is not None and ticket_ref:
        row.ticket_ref = ticket_ref
        await session.flush()


async def prune_media(session: AsyncSession, tenant_id: str) -> int:
    from voiceai.modules.evidence import media

    return await media.prune_expired(session, tenant_id)
