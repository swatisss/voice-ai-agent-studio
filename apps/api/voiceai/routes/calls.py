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

from voiceai.config import get_settings
from voiceai.db import get_session, sessionmaker
from voiceai.errors import ApiError
from voiceai.live import LIVE, LiveControls, effective_settings, persona_dict
from voiceai.models import AgentVersion, Call, CallAnalysis, CallEvent, Escalation, Persona
from voiceai.schemas import TurnDetectionPatch
from voiceai.runtime import escalation as esc_mod
from voiceai.runtime.session import AgentSession, create_call
from voiceai.tenancy import current_tenant, resolve_tenant

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


def call_summary(c: Call, analysis: CallAnalysis | None = None, version: int | None = None) -> dict[str, Any]:
    return {
        "id": c.id, "agent_id": c.agent_id, "agent_version_id": c.agent_version_id, "agent_version": version,
        "channel": c.channel, "direction": c.direction, "status": c.status, "outcome": c.outcome, "caller_ref": c.caller_ref,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "ended_at": c.ended_at.isoformat() if c.ended_at else None, "end_reason": c.end_reason,
        "turn_count": c.turn_count, "tokens_in": c.tokens_in, "tokens_out": c.tokens_out,
        "llm_cost_usd": c.llm_cost_usd, "latency_p50_ms": c.latency_p50_ms, "is_seed": c.is_seed,
        "intent": analysis.intent if analysis else None, "root_cause": analysis.root_cause if analysis else None,
    }


def analysis_out(a: CallAnalysis | None) -> dict[str, Any] | None:
    if not a:
        return None
    return {k: getattr(a, k) for k in ("outcome", "intent", "root_cause", "fixable", "gap_summary", "caller_goal",
                                        "resolution_summary", "sentiment_start", "sentiment_end", "cluster_id", "source")}


@router.post("/calls")
async def start_call(body: CallCreate, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    live: dict = {}
    if body.persona_id:
        await _persona(s, tenant_id, body.persona_id)
        live["persona_id"] = body.persona_id
    if body.turn_detection:
        live["turn_detection"] = body.turn_detection.model_dump(exclude_none=True)
    call = await create_call(s, tenant_id, body.agent_id, body.channel, live=live or None, context=body.context, app=request.app)
    await s.commit()
    greeting = None
    if body.channel == "text":
        session = await AgentSession.open(call.id, tenant_id, app=request.app)
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
    session = await AgentSession.open(call_id, tenant_id, app=request.app)
    controls = LIVE.get(call_id)
    if body.persona_id is not None:
        await session.switch_persona(persona_dict(persona) if persona else None)
        voice = session.config.get("persona") or {}
        if controls and controls.on_voice:
            await controls.on_voice(voice.get("voice", "aura-2-thalia-en"), float(voice.get("speed", 1.0)))
    if body.turn_detection is not None:
        await session.change_turn_detection(body.turn_detection.model_dump(exclude_none=True))
        if controls:
            controls.turn = session.turn_settings()
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
    session = await AgentSession.open(call_id, tenant_id, app=request.app)
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
        session = await AgentSession.open(call_id, tenant_id, app=request.app)
        await session.end("hangup")
    async with sessionmaker()() as s2:
        fresh = await s2.get(Call, call_id)
        return {"status": fresh.status, "outcome": fresh.outcome}


@router.get("/calls")
async def list_calls(
    agent_id: str | None = None, outcome: str | None = None, channel: str | None = None, direction: str | None = None,
    include_seed: bool = True, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session),
) -> dict:
    q = (
        select(Call, CallAnalysis, AgentVersion.version)
        .outerjoin(CallAnalysis, CallAnalysis.call_id == Call.id)
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
    if not include_seed:
        q = q.where(Call.is_seed.is_(False))
    rows = (await s.execute(q)).all()
    return {"items": [call_summary(c, a, v) for c, a, v in rows]}


@router.get("/calls/{call_id}")
async def call_detail(call_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if not call:
        raise ApiError(404, "call_not_found", "Call not found")
    events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all()
    esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
    analysis = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
    version = await s.get(AgentVersion, call.agent_version_id)
    return {
        **call_summary(call, analysis, version.version if version else None),
        "events": [{"seq": e.seq, "at": e.at.isoformat(), "kind": e.kind, "text": e.text, "data": e.data} for e in events],
        "escalation": esc_mod.summary(esc) if esc else None,
        "analysis": analysis_out(analysis),
        "settings": await effective_settings(s, call),
    }


@router.websocket("/voice/{call_id}")
async def voice(websocket: WebSocket, call_id: str) -> None:
    await websocket.accept()
    async with sessionmaker()() as s:
        try:
            tenant_id = await resolve_tenant(s, websocket.query_params.get("tenant"))
        except ApiError:
            await websocket.close(code=4404, reason="unknown tenant")
            return
        call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if not call or call.ended_at:  # VO-04
        await websocket.close(code=4404, reason="unknown or ended call")
        return
    if call.channel != "voice":
        await websocket.close(code=4400, reason="wrong channel")
        return
    key = get_settings().deepgram_api_key
    if not key:  # VO-05
        await websocket.close(code=4500, reason="voice_unavailable")
        return
    try:
        from voiceai.voice import pipeline
    except Exception as exc:  # noqa: BLE001
        log.error("voice pipeline unavailable: %s", exc)
        await websocket.close(code=4500, reason="voice_unavailable")
        return
    session = await AgentSession.open(call_id, tenant_id, app=websocket.app)
    controls = LiveControls(turn=session.turn_settings())
    LIVE[call_id] = controls
    try:
        await pipeline.run(websocket, session, key, controls)
    finally:
        LIVE.pop(call_id, None)
