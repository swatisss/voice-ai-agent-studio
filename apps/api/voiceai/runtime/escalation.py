"""Escalation: safety screen, escalation rows, groundwork packets, console lifecycle.

Spec: /architecture/escalation.md, /prompts/escalation-packet.md
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core import jobs, prompts
from voiceai.core.db import sessionmaker, utcnow
from voiceai.core.errors import ApiError
from voiceai.core.events import bus
from voiceai.core.llm.gateway import gateway
from voiceai.core.tables import Call, CallEvent, Escalation
from voiceai.schemas import DISPOSITIONS, Packet

log = logging.getLogger("voiceai.escalation")

SAFETY_PHRASES = (
    "suicide", "kill myself", "end my life", "hurt myself", "want to die", "overdose", "chest pain",
    "can't breathe", "cannot breathe", "stroke", "unconscious", "severe bleeding", "heart attack",
)
SAFETY_MESSAGE = (
    "If this is a medical emergency, please hang up and call 911. If you are thinking about harming yourself, "
    "you can call or text 988 at any time. I'm connecting you with a nurse right now."
)

_packet_tasks: set[asyncio.Task[None]] = set()


def safety_match(text: str) -> bool:
    t = text.lower().replace("’", "'")
    return any(p in t for p in SAFETY_PHRASES)


def summary(e: Escalation) -> dict[str, Any]:
    return {
        "id": e.id, "call_id": e.call_id, "agent_id": e.agent_id, "status": e.status,
        "reason_category": e.reason_category, "reason_detail": e.reason_detail,
        "packet_status": e.packet_status, "packet": e.packet, "assignee": e.assignee,
        "disposition": e.disposition, "resolution_note": e.resolution_note,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "accepted_at": e.accepted_at.isoformat() if e.accepted_at else None,
        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
    }


async def create(
    tenant_id: str, call_id: str, agent_id: str, category: str, detail: str,
    tools_used: list[dict[str, Any]], verified_ref: str | None, is_eval: bool = False,
) -> str:
    """Create the escalation row (idempotent per call) and start the packet build (ES-04, ES-08).

    Evaluation (simulated) calls never reach the human console: no console events, deterministic packet only.
    """
    async with sessionmaker()() as s:
        existing = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        if existing:
            return existing.id
        esc = Escalation(tenant_id=tenant_id, call_id=call_id, agent_id=agent_id, reason_category=category, reason_detail=detail)
        s.add(esc)
        call = await s.get(Call, call_id)
        if call and call.status == "active":
            call.status = "escalated"
        if is_eval:
            esc.packet = fallback_packet(esc, [], tools_used, verified_ref)
            esc.packet_status = "fallback"
            await s.commit()
            return esc.id
        await s.commit()
        data = summary(esc)
    bus.publish(tenant_id, "console", "escalation.created", data)
    bus.publish(tenant_id, f"call:{call_id}", "call.escalated", {"call_id": call_id, "escalation_id": data["id"], "reason_category": category})
    task = asyncio.create_task(build_packet(data["id"], tools_used, verified_ref))
    _packet_tasks.add(task)
    task.add_done_callback(_packet_tasks.discard)
    return data["id"]


async def wait_packets() -> None:
    """Await in-flight packet builds (tests, shutdown)."""
    while _packet_tasks:
        await asyncio.gather(*list(_packet_tasks), return_exceptions=True)


def transcript_lines(events: list[CallEvent]) -> str:
    lines = []
    for ev in events:
        if ev.kind == "user":
            lines.append(f"Caller: {ev.text}")
        elif ev.kind == "assistant" and ev.text:
            lines.append(f"Agent: {ev.text}")
        elif ev.kind == "tool_result":
            lines.append(f"Tool {ev.data.get('name')} -> {str(ev.data.get('result'))[:400]}")
    return "\n".join(lines)


def fallback_packet(esc: Escalation, events: list[CallEvent], tools_used: list[dict[str, Any]], verified_ref: str | None) -> dict[str, Any]:
    callers = [e.text for e in events if e.kind == "user" and e.text]
    return Packet(
        summary=" ".join(callers[-2:]) or "No caller speech recorded.",
        intent="unknown",
        entities={"member_ref": verified_ref} if verified_ref else {},
        already_tried=[t["summary"] for t in tools_used],
        escalation_reason={"category": esc.reason_category, "detail": esc.reason_detail},
        sentiment={"start": "neutral", "end": "neutral", "trend": "stable"},
        suggested_next_action="Review the transcript and confirm the caller's request.",
        caller_verified=bool(verified_ref),
    ).model_dump()


async def build_packet(escalation_id: str, tools_used: list[dict[str, Any]], verified_ref: str | None) -> None:
    async with sessionmaker()() as s:
        esc = await s.get(Escalation, escalation_id)
        if esc is None:
            return
        events = list((await s.scalars(select(CallEvent).where(CallEvent.call_id == esc.call_id).order_by(CallEvent.seq))).all())
        try:
            prompt = prompts.render(
                "escalation-packet",
                transcript=transcript_lines(events) or "(empty)",
                tools_used="\n".join(f"- {t['summary']}" for t in tools_used) or "- (none)",
                reason_category=esc.reason_category,
                reason_detail=esc.reason_detail,
                verified="yes" if verified_ref else "no",
                member_ref=verified_ref or "",
            )
            packet, _ = await gateway().complete_json("analysis", [{"role": "user", "content": prompt}], Packet)
            data = packet.model_dump()
            data["escalation_reason"]["category"] = esc.reason_category
            data["caller_verified"] = bool(verified_ref)
            esc.packet, esc.packet_status = data, "ready"
        except Exception as exc:  # noqa: BLE001 - ES-05 any failure -> deterministic packet
            log.warning("packet LLM failed for %s: %s", escalation_id, exc)
            esc.packet, esc.packet_status = fallback_packet(esc, events, tools_used, verified_ref), "fallback"
        await s.commit()
        bus.publish(esc.tenant_id, "console", "escalation.updated", summary(esc))


async def get_owned(s: AsyncSession, tenant_id: str, escalation_id: str) -> Escalation:
    esc = await s.scalar(select(Escalation).where(Escalation.id == escalation_id, Escalation.tenant_id == tenant_id))
    if not esc:
        raise ApiError(404, "escalation_not_found", "Escalation not found")
    return esc


async def accept(s: AsyncSession, tenant_id: str, escalation_id: str, assignee: str) -> Escalation:
    esc = await get_owned(s, tenant_id, escalation_id)
    if esc.status != "waiting":
        raise ApiError(409, "invalid_state", f"Escalation is {esc.status}, not waiting")
    esc.status, esc.assignee, esc.accepted_at = "accepted", (assignee or "Specialist")[:120], utcnow()
    await s.commit()
    bus.publish(tenant_id, "console", "escalation.updated", summary(esc))
    return esc


async def resolve(s: AsyncSession, tenant_id: str, escalation_id: str, disposition: str, note: str) -> Escalation:
    esc = await get_owned(s, tenant_id, escalation_id)
    if esc.status != "accepted":  # ES-06
        raise ApiError(409, "invalid_state", "Accept the escalation before resolving it")
    if disposition not in DISPOSITIONS:
        raise ApiError(422, "invalid_disposition", f"Disposition must be one of {', '.join(DISPOSITIONS)}")
    if len((note or "").strip()) < 10:  # ES-07
        raise ApiError(422, "note_too_short", "Resolution note must be at least 10 characters")
    esc.status, esc.disposition, esc.resolution_note, esc.resolved_at = "resolved", disposition, note.strip(), utcnow()
    call = await s.get(Call, esc.call_id)
    # FL-08: re-analyze once so the analysis captures the human resolution
    if call and call.ended_at is not None:
        await jobs.enqueue(s, tenant_id, "analyze_call", {"call_id": esc.call_id}, dedupe_key=f"analyze_call:{esc.call_id}:2")
    await s.commit()
    bus.publish(tenant_id, "console", "escalation.updated", summary(esc))
    return esc
