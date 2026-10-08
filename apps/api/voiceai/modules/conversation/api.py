"""Calls: create, text messages, end, explorer, detail, and the voice WebSocket.

Spec: /api/rest-api.md (Calls), /api/voice-protocol.md, /architecture/agent-runtime.md
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, WebSocket
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.config import get_settings
from voiceai.core.db import get_session, sessionmaker
from voiceai.core.errors import ApiError
from voiceai.modules.agentcfg.contract import effective_settings, persona_dict
from voiceai.core import jobs
from voiceai.core.db import utcnow
from voiceai.core.handoff import handoff_desk
from voiceai.core.postcall import post_call_analysis
from voiceai.core.tables import AgentVersion, Call, CallAnalysis, CallEvent, CallFeedback, Persona
from voiceai.modules.agentcfg.contract import TurnDetectionPatch
from voiceai.core.toolcalling import tool_caller
from voiceai.core.voicecontrol import voice_control
from voiceai.modules.conversation.serializers import analysis_out, call_summary, feedback_out
from voiceai.modules.conversation.session import AgentSession, create_call
from voiceai.core.tenancy import current_tenant, resolve_tenant

log = logging.getLogger("voiceai.calls")
router = APIRouter(prefix="/api")


class CallCreate(BaseModel):
    agent_id: str
    channel: Literal["voice", "text"] = "text"
    persona_id: str | None = None
    turn_detection: TurnDetectionPatch | None = None
    context: dict[str, Any] | None = None  # outbound agents: {member_ref} of a listed target (OB-01)


class LiveBody(BaseModel):
    persona_id: str | None = None          # "" restores the agent's own persona
    turn_detection: TurnDetectionPatch | None = None


async def _persona(s: AsyncSession, tenant_id: str, persona_id: str) -> Persona:
    row = await s.scalar(select(Persona).where(Persona.id == persona_id, Persona.tenant_id == tenant_id))
    if row is None:  # PER-06
        raise ApiError(404, "persona_not_found", "Persona not found")
    return row


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class FeedbackBody(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=300)


@router.post("/calls")
async def start_call(body: CallCreate, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    live: dict = {}
    if body.persona_id:
        await _persona(s, tenant_id, body.persona_id)
        live["persona_id"] = body.persona_id
    if body.turn_detection:
        live["turn_detection"] = body.turn_detection.model_dump(exclude_none=True)
    call = await create_call(s, tenant_id, body.agent_id, body.channel, live=live or None, context=body.context, caller=tool_caller(request.app))
    await s.commit()
    greeting = None
    if body.channel == "text":
        session = await AgentSession.open(call.id, tenant_id, caller=tool_caller(request.app))
        greeting = await session.start()
    return {"call_id": call.id, "greeting": greeting, "settings": await effective_settings(s, call)}


@router.patch("/calls/{call_id}/live")
async def live_settings(call_id: str, body: LiveBody, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    """Change persona and/or turn detection of a running call (PER-04, TD-06)."""
    call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if not call:
        raise ApiError(404, "call_not_found", "Call not found")
    if call.ended_at:
        raise ApiError(409, "call_ended", "This call has ended")
    persona = await _persona(s, tenant_id, body.persona_id) if body.persona_id else None
    await s.close()
    session = await AgentSession.open(call_id, tenant_id, caller=tool_caller(request.app))
    live = voice_control()  # a text call, or a voice call on another instance, simply is not there
    if body.persona_id is not None:
        await session.switch_persona(persona_dict(persona) if persona else None)
        voice = session.config.get("persona") or {}
        await live.set_voice(call_id, voice.get("voice", "aura-2-thalia-en"), float(voice.get("speed", 1.0)))
    if body.turn_detection is not None:
        await session.change_turn_detection(body.turn_detection.model_dump(exclude_none=True))
        live.set_turn(call_id, session.turn_settings().to_dict())
    return {"settings": session.settings()}


@router.post("/calls/{call_id}/messages")
async def message(call_id: str, body: MessageBody, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if not call:
        raise ApiError(404, "call_not_found", "Call not found")
    if call.channel != "text":  # API-02
        raise ApiError(409, "wrong_channel", "Messages can only be sent to text calls")
    if call.ended_at:
        raise ApiError(409, "call_ended", "This call has ended")
    await s.close()
    session = await AgentSession.open(call_id, tenant_id, caller=tool_caller(request.app))
    reply = await session.reply(body.text)
    status = "ended" if session.state.ended else ("escalated" if session.state.escalated else "active")
    return {"reply": reply, "call_status": status, "ended": session.state.ended, "escalated": session.state.escalated}


@router.post("/calls/{call_id}/end")
async def end_call(call_id: str, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if not call:
        raise ApiError(404, "call_not_found", "Call not found")
    await s.close()
    if not call.ended_at:
        session = await AgentSession.open(call_id, tenant_id, caller=tool_caller(request.app))
        await session.end("hangup")
    async with sessionmaker()() as s2:
        fresh = await s2.get(Call, call_id)
        return {"status": fresh.status, "outcome": fresh.outcome}


@router.post("/calls/{call_id}/feedback")
async def give_feedback(call_id: str, body: FeedbackBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    """FB-01, FB-02, FB-03: the caller's thumbs up or down after the call; a thumbs down queues one more analysis."""
    call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if not call:
        raise ApiError(404, "call_not_found", "Call not found")
    if call.is_eval or call.channel == "simulation":
        raise ApiError(409, "not_ratable", "Simulated calls cannot be rated")
    if not call.ended_at:
        raise ApiError(409, "call_active", "Feedback can be given once the call has ended")
    comment = (body.comment or "").strip() or None
    row = await s.scalar(select(CallFeedback).where(CallFeedback.call_id == call_id))
    if row is None:
        row = CallFeedback(tenant_id=tenant_id, call_id=call_id, agent_id=call.agent_id, rating=body.rating, comment=comment)
        s.add(row)
    else:
        row.rating, row.comment, row.updated_at = body.rating, comment, utcnow()
    if body.rating == "down":  # the analysis must see the feedback (FB-03); the dedupe key means one extra run per call
        await post_call_analysis().request(s, tenant_id, call_id, "caller_feedback")
    await s.commit()
    return {"rating": row.rating, "comment": row.comment or ""}


@router.get("/calls")
async def list_calls(
    agent_id: str | None = None, outcome: str | None = None, channel: str | None = None, direction: str | None = None,
    feedback: Literal["up", "down", "none"] | None = None,
    include_seed: bool = True, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session),
) -> dict:
    q = (
        select(Call, CallAnalysis, AgentVersion.version, CallFeedback.rating)
        .outerjoin(CallAnalysis, CallAnalysis.call_id == Call.id)
        .outerjoin(CallFeedback, CallFeedback.call_id == Call.id)
        .outerjoin(AgentVersion, AgentVersion.id == Call.agent_version_id)
        .where(Call.tenant_id == tenant_id, Call.is_eval.is_(False))  # API-04
        .order_by(Call.started_at.desc())
        .limit(500)
    )
    if agent_id:
        q = q.where(Call.agent_id == agent_id)
    if outcome:
        q = q.where(Call.outcome == outcome)
    if channel:
        q = q.where(Call.channel == channel)
    if direction:
        q = q.where(Call.direction == direction)
    if feedback == "none":  # FB-05
        q = q.where(CallFeedback.rating.is_(None))
    elif feedback:
        q = q.where(CallFeedback.rating == feedback)
    if not include_seed:
        q = q.where(Call.is_seed.is_(False))
    rows = (await s.execute(q)).all()
    return {"items": [call_summary(c, a, v, f) for c, a, v, f in rows]}


@router.get("/calls/{call_id}")
async def call_detail(call_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if not call:
        raise ApiError(404, "call_not_found", "Call not found")
    events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all()
    analysis = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
    version = await s.get(AgentVersion, call.agent_version_id)
    fb = await s.scalar(select(CallFeedback).where(CallFeedback.call_id == call_id))
    return {
        **call_summary(call, analysis, version.version if version else None, fb.rating if fb else None),
        "feedback": feedback_out(fb),  # detail carries the object; the summary carries just the rating
        "events": [{"seq": e.seq, "at": e.at.isoformat(), "kind": e.kind, "text": e.text, "data": e.data} for e in events],
        "escalation": await handoff_desk().for_call(s, tenant_id, call_id),
        "analysis": analysis_out(analysis),
        "settings": await effective_settings(s, call),
    }
