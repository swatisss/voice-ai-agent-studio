"""Conversations: one caller connection, one call (segment) per agent; shared by the public API and the playground.

Spec: /api/public-api.md, /api/rest-api.md (Conversations), /architecture/supervisor-routing.md (Conversations),
/architecture/agent-transfer.md, /architecture/webhooks.md, /architecture/multi-tenancy.md (rule 10)
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import admission, caller_id, voice_calls, webhooks
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.models import Agent, AgentVersion, Call, CallEvent, CallScorecard, Conversation, Escalation
from voiceai.public import keys as key_mod
from voiceai.public import tokens
from voiceai.schemas import E164_RE

log = logging.getLogger("voiceai.conversations")

CONTEXT_KEY = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
MAX_CONTEXT = 10
MAX_CONTEXT_VALUE = 200
MAX_METADATA_BYTES = 4096
VOICE_TRANSPORTS = ("websocket", "media-stream", "webrtc")
SOCKET_PATH = {"websocket": "voice", "media-stream": "media-stream"}


class Caller(BaseModel):
    number: str | None = Field(default=None, max_length=20)

    @field_validator("number")
    @classmethod
    def _e164(cls, v: str | None) -> str | None:
        if v is not None and not E164_RE.fullmatch(v.strip()):
            raise ValueError("caller.number must be an E.164 number such as +12025550141")
        return v.strip() if v else None


class CreateBody(BaseModel):
    channel: Literal["text", "voice"]
    message: str | None = Field(default=None, max_length=2000)
    agent_id: str | None = None
    transport: Literal["websocket", "media-stream", "webrtc"] | None = None
    audio_format: Literal["mulaw_8k", "pcm_16k"] | None = None
    caller: Caller | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    external_id: str | None = Field(default=None, max_length=128)

    @field_validator("context")
    @classmethod
    def _context(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return None
        if len(v) > MAX_CONTEXT:
            raise ValueError(f"context holds at most {MAX_CONTEXT} entries")
        for key, value in v.items():
            if not CONTEXT_KEY.fullmatch(key):
                raise ValueError(f"context key '{key}' must match {CONTEXT_KEY.pattern}")
            if len(str(value)) > MAX_CONTEXT_VALUE:
                raise ValueError(f"context value of '{key}' is longer than {MAX_CONTEXT_VALUE} characters")
        return {k: str(val) for k, val in v.items()}

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v)) > MAX_METADATA_BYTES:
            raise ValueError("metadata must be at most 4 KB of JSON")
        return v


# ---------------------------------------------------------------- agents in scope
def in_scope(config: dict[str, Any], scope: str) -> bool:
    return config.get("mode", "inbound") == key_mod.SCOPE_MODE.get(scope)


async def scoped_agents(s: AsyncSession, tenant_id: str, scope: str, routable_only: bool = True) -> list[tuple[Agent, AgentVersion]]:
    """Published agents of the scope's mode (PUB-03); with `routable_only`, those whose snapshot allows routing."""
    rows = (await s.execute(
        select(Agent, AgentVersion).join(AgentVersion, AgentVersion.id == Agent.published_version_id)
        .where(Agent.tenant_id == tenant_id).order_by(Agent.name))).all()
    return [(a, v) for a, v in rows if in_scope(v.config, scope) and (not routable_only or v.config.get("routable", True))]


async def scoped_agent(s: AsyncSession, tenant_id: str, scope: str, agent_id: str) -> tuple[Agent, AgentVersion]:
    """An agent reachable with this scope, else 404 `agent_not_found` (unpublished, other scope, outbound, other tenant)."""
    agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    version = await s.get(AgentVersion, agent.published_version_id) if agent and agent.published_version_id else None
    if not agent or not version or not in_scope(version.config, scope):
        raise ApiError(404, "agent_not_found", "Agent not found")
    return agent, version


# ---------------------------------------------------------------- views
def agent_ref(agent: Agent | None) -> dict[str, Any] | None:
    return {"id": agent.id, "name": agent.name} if agent else None


async def _segments(s: AsyncSession, conv: Conversation) -> list[Call]:
    return list((await s.scalars(select(Call).where(Call.conversation_id == conv.id, Call.tenant_id == conv.tenant_id).order_by(Call.segment))).all())


async def _agent_names(s: AsyncSession, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    return {a.id: a.name for a in (await s.scalars(select(Agent).where(Agent.id.in_(ids)))).all()}


async def transcript(s: AsyncSession, conv: Conversation) -> list[dict[str, Any]]:
    """PUB-10: caller, front-desk and agent lines with their segment numbers; no tool calls."""
    calls = await _segments(s, conv)
    names = await _agent_names(s, {c.agent_id for c in calls})
    lines: list[dict[str, Any]] = []
    for c in calls:
        events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == c.id, CallEvent.kind.in_(("user", "assistant"))).order_by(CallEvent.seq))).all()
        for e in events:
            if not e.text:
                continue
            if e.kind == "user":
                speaker = "caller"
            else:
                speaker = "front_desk" if (e.data or {}).get("front_desk") else "agent"
            line = {"segment": c.segment, "speaker": speaker, "text": e.text, "at": e.at.isoformat()}
            if speaker == "agent":
                line.update({"agent_id": c.agent_id, "agent_name": names.get(c.agent_id)})
            lines.append(line)
    return lines


async def _escalation_of(s: AsyncSession, conv: Conversation) -> dict[str, Any] | None:
    row = await s.scalar(select(Escalation).join(Call, Call.id == Escalation.call_id)
                         .where(Call.conversation_id == conv.id, Escalation.tenant_id == conv.tenant_id).order_by(Escalation.created_at.desc()))
    return {"id": row.id, "status": row.status} if row else None


async def view(s: AsyncSession, conv: Conversation, include_transcript: bool = False) -> dict[str, Any]:
    calls = await _segments(s, conv)
    names = await _agent_names(s, {c.agent_id for c in calls})
    current = next((c for c in calls if c.id == conv.current_call_id), None)
    out = {
        "id": conv.id, "status": conv.status, "channel": conv.channel, "transport": conv.transport, "source": conv.source,
        "scope": conv.scope, "external_id": conv.external_id, "metadata": conv.metadata_ or {},
        "started_at": conv.started_at.isoformat(), "ended_at": conv.ended_at.isoformat() if conv.ended_at else None,
        "outcome": conv.outcome, "end_reason": conv.end_reason,
        "agent": {"id": current.agent_id, "name": names.get(current.agent_id)} if current else None,
        "segments": [{"call_id": c.id, "agent_id": c.agent_id, "agent_name": names.get(c.agent_id), "segment": c.segment,
                      "routed_by": c.routed_by, "started_at": c.started_at.isoformat() if c.started_at else None,
                      "ended_at": c.ended_at.isoformat() if c.ended_at else None, "outcome": c.outcome} for c in calls],
        "routing": list(conv.routing or []),
        "escalation": await _escalation_of(s, conv),
    }
    if include_transcript:
        out["transcript"] = await transcript(s, conv)
    return out


async def get(s: AsyncSession, tenant_id: str, conversation_id: str, source: str | None = None) -> Conversation:
    q = select(Conversation).where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
    conv = await s.scalar(q)
    if conv is None or (source == "api" and conv.source != "api"):  # MT-15; a key sees only API conversations
        raise ApiError(404, "conversation_not_found", "Conversation not found")
    return conv


# ---------------------------------------------------------------- create
def connect_info(conv: Conversation, base_url: str | None = None) -> dict[str, Any]:
    """The URL and single-use token a voice client opens (PUB-07)."""
    token, expires = tokens.mint(conv.tenant_id, conv.id, conv.transport)
    base = (get_settings().public_base_url or base_url or "").rstrip("/")
    ws_base = ("wss://" if base.startswith("https://") else "ws://") + base.split("://", 1)[-1]
    from datetime import datetime, timezone

    info: dict[str, Any] = {"token": token, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(), "protocol": tokens.SUBPROTOCOL}
    if conv.transport in SOCKET_PATH:
        info["url"] = f"{ws_base}/v1/{SOCKET_PATH[conv.transport]}/{conv.id}"
    if conv.transport == "webrtc":  # /architecture/webrtc-transport.md (Connect)
        from voiceai.public import webrtc

        http_base = base if base.startswith("http") else "https://" + base.split("://", 1)[-1]
        info.update(offer_url=f"{http_base}/v1/webrtc/{conv.id}/offer", ice_servers=webrtc.ice_servers())
    return info


async def active_voice(s: AsyncSession, api_key_id: str) -> int:
    return await s.scalar(select(func.count()).select_from(Conversation).where(
        Conversation.api_key_id == api_key_id, Conversation.channel == "voice", Conversation.status != "ended")) or 0


async def start_segment(s: AsyncSession, conv: Conversation, agent_id: str, routed_by: str, app: Any, *,
                        context: dict[str, Any] | None = None, identification: dict[str, Any] | None = None,
                        meta: dict[str, Any] | None = None) -> Call:
    """A new call for `agent_id` as the next segment of the conversation (not committed)."""
    from voiceai.runtime.session import create_call

    n = await s.scalar(select(func.count()).select_from(Call).where(Call.conversation_id == conv.id)) or 0
    call = await create_call(s, conv.tenant_id, agent_id, conv.channel, app=app)
    call.conversation_id, call.segment, call.routed_by = conv.id, n + 1, routed_by
    extra: dict[str, Any] = dict(meta or {})
    if context:
        extra["context"] = {**((call.meta or {}).get("context") or {}), **context}
    if identification:
        extra["identification"] = identification
    if extra:
        call.meta = {**(call.meta or {}), **extra}
    conv.current_call_id = call.id
    return call


async def create(s: AsyncSession, tenant_id: str, body: CreateBody, *, source: str, scope: str, app: Any,
                 api_key_id: str | None = None, max_concurrent_voice: int | None = None, base_url: str | None = None) -> dict[str, Any]:
    """Create a conversation and its first segment; text answers at once, voice returns `connect` (PUB-05, PUB-07)."""
    if body.channel == "text" and (body.transport or body.audio_format):
        raise ApiError(422, "validation_error", "transport and audio_format apply to voice conversations only")
    transport = (body.transport or "websocket") if body.channel == "voice" else "text"
    if body.audio_format and transport != "media-stream":
        raise ApiError(422, "validation_error", "audio_format applies to the media-stream transport only")
    if body.channel == "voice" and body.message:
        raise ApiError(422, "validation_error", "message applies to text conversations only")
    if transport == "webrtc":  # WRTC-03: on Cloud Run a TURN relay is required
        from voiceai.public import webrtc

        if not webrtc.available():
            raise ApiError(503, "webrtc_unavailable", "WebRTC needs a TURN relay on this server (WEBRTC_TURN_URLS)")
    if body.agent_id:
        await scoped_agent(s, tenant_id, scope, body.agent_id)
    else:  # routed by the supervisor (/architecture/supervisor-routing.md)
        from voiceai.routing import supervisor

        if not await supervisor.candidates(s, tenant_id, scope):
            raise ApiError(409, "no_routable_agents", "No agent can take conversations for this audience yet")
    if body.channel == "voice":
        if not get_settings().public_api_secret:
            raise ApiError(503, "voice_tokens_unavailable", "Voice connections are not configured on this server (PUBLIC_API_SECRET)")
        if api_key_id and max_concurrent_voice is not None:
            await expire_unconnected(tenant_id)
            if await active_voice(s, api_key_id) >= max_concurrent_voice:  # PUB-04
                raise ApiError(429, "voice_capacity", f"This key already has {max_concurrent_voice} active voice conversations",
                               {"Retry-After": "30"})
    identification = None
    if body.caller and body.caller.number and scope == "member":  # PUB-09: only the identification is kept
        match = await caller_id.identify(body.caller.number, app)
        identification = caller_id.identification(match) if match else None

    settings: dict[str, Any] = {"audio_format": body.audio_format or "mulaw_8k"} if transport == "media-stream" else {}
    conv = Conversation(tenant_id=tenant_id, source=source, api_key_id=api_key_id, channel=body.channel, transport=transport,
                        scope=scope, external_id=body.external_id, metadata_=body.metadata or {}, settings=settings)
    s.add(conv)
    await s.flush()
    call: Call | None = None
    greeting = ""
    if body.agent_id:  # RTE-10: no routing request
        call = await start_segment(s, conv, body.agent_id, "explicit", app, context=body.context, identification=identification)
        conv.routing = [{"at": utcnow().isoformat(), "trigger": "start", "method": "explicit", "agent_id": body.agent_id,
                         "confidence": None, "reason": "agent_id given", "candidates": [], "stage_b": None, "fallbacks": []}]
        if body.channel == "voice":
            decided = await voice_calls.admit(s, tenant_id, call)
            if isinstance(decided, admission.Refusal):
                await s.rollback()
                raise _refused(decided)
    else:
        greeting = await open_front_desk(s, conv, context=body.context, identification=identification)
        if body.channel == "voice":
            decided = await admission.admit(s, tenant_id, await front_desk_config(s, conv))
            if isinstance(decided, admission.Refusal):
                await s.rollback()
                raise _refused(decided)
            conv.settings = {**conv.settings, "admission": decided.to_meta()}
    await webhooks.emit(s, conv, "conversation.started", {"channel": conv.channel, "transport": conv.transport})
    await s.commit()
    result: dict[str, Any] = {"conversation_id": conv.id, "status": conv.status, "channel": conv.channel}
    if call is not None:
        agent = await s.get(Agent, body.agent_id)
        if body.channel == "text":
            messages = await _open_text(conv, call, body.message, app)
            await s.refresh(conv)
            result.update(status=conv.status, agent=agent_ref(agent), routing=_routing_out(conv.routing[-1]), messages=messages)
        else:
            result.update(transport=transport, agent=agent_ref(agent), routing=_routing_out(conv.routing[-1]), connect=connect_info(conv, base_url))
        return result
    if body.channel == "voice":
        result.update(transport=transport, agent=None, routing=None, connect=connect_info(conv, base_url))
        return result
    messages = [{"speaker": "front_desk", "text": greeting}]
    if body.message and body.message.strip():
        turn = await routed_text_turn(conv.id, tenant_id, body.message, app)
        return {**result, "status": turn["status"], "agent": turn["agent"], "routing": turn["routing"], "messages": messages + turn["messages"]}
    return {**result, "agent": None, "routing": None, "messages": messages}


def _refused(decided: admission.Refusal) -> ApiError:
    return ApiError(409, decided.reason, "Voice is not available for this agent right now"
                    if decided.reason == "voice_unavailable" else "The voice pipeline is not enabled for this business unit")


# ---------------------------------------------------------------- the front desk (/architecture/supervisor-routing.md)
async def open_front_desk(s: AsyncSession, conv: Conversation, *, context: dict[str, Any] | None = None,
                          identification: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> str:
    """Remember the front desk's persona and pipeline on the conversation and record its greeting (not committed)."""
    from voiceai.routing import front_desk

    fd = await front_desk.load(s, conv.tenant_id)
    persona = await front_desk.persona(s, conv.tenant_id, fd)
    greeting = f"{persona.get('greeting', '').strip()} {persona.get('disclosure', '').strip()}".strip()
    conv.settings = {**(conv.settings or {}), "front_desk": {"persona_id": persona.get("id"), "pipeline": fd.pipeline},
                     "front_desk_events": [{"kind": "assistant", "text": greeting}],
                     "context": context or {}, "identification": identification, **(extra or {})}
    return greeting


async def front_desk_config(s: AsyncSession, conv: Conversation) -> dict[str, Any]:
    """The config of the front-desk phase: its persona and pipeline, no tools."""
    from voiceai.routing import front_desk

    fd = await front_desk.load(s, conv.tenant_id)
    persona = await front_desk.persona(s, conv.tenant_id, fd)
    pipeline = ((conv.settings or {}).get("front_desk") or {}).get("pipeline") or fd.pipeline
    return {"mode": "inbound", "persona": persona, "policy": {}, "tools": [], "skills": [], "knowledge_doc_ids": [],
            "models": {"realtime": None, "speech": None}, "voice": {"pipeline": pipeline, "realtime": {"voice": None}}}


def intro_line(config: dict[str, Any], agent_name: str) -> str:
    from voiceai.schemas import DEFAULT_HANDOFF_INTRO

    return (config.get("handoff_intro") or DEFAULT_HANDOFF_INTRO).replace("{agent_name}", agent_name).strip()


NO_ROUTE_LINE = "I'm sorry, nobody can take this request right now. Please try again later."


async def front_desk_turn(conv_id: str, tenant_id: str, text: str, app: Any) -> dict[str, Any]:
    """One caller turn before an agent is chosen: ask a clarifying question, or start the first segment (RTE-05, RTE-07)."""
    from voiceai.events import bus
    from voiceai.routing import supervisor
    from voiceai.runtime.session import AgentSession

    async with sessionmaker()() as s:
        conv = await get(s, tenant_id, conv_id)
        earlier = [e["text"] for e in (conv.settings or {}).get("front_desk_events", []) if e["kind"] == "user"]
        clarified, scope, channel = conv.clarifications, conv.scope, conv.channel
    request = " ".join([*earlier, text]) if clarified else text
    record = await supervisor.route(tenant_id, scope, request, channel=channel, clarifications_used=clarified)
    topic = f"conversation:{conv_id}"
    async with sessionmaker()() as s:
        conv = await get(s, tenant_id, conv_id)
        settings = dict(conv.settings or {})
        events = list(settings.get("front_desk_events", []))
        if record["method"] == "clarify":
            settings["front_desk_events"] = events + [{"kind": "user", "text": text}, {"kind": "assistant", "text": record["clarification"]}]
            conv.settings, conv.clarifications = settings, conv.clarifications + 1
            conv.routing = [*(conv.routing or []), record]
            await s.commit()
            bus.publish(tenant_id, topic, "routing.decision", {"conversation_id": conv_id, "decision": record})
            return {"kind": "clarify", "line": record["clarification"], "record": record}
        if record["agent_id"] is None:
            conv.routing = [*(conv.routing or []), record]
            conv.status, conv.end_reason, conv.outcome, conv.ended_at = "ended", "error", "abandoned", utcnow()
            await s.commit()
            return {"kind": "none", "line": NO_ROUTE_LINE, "record": record}
        if clarified and record["method"] in ("single", "embedding", "decision", "llm"):
            record = {**record, "decided_by": record["method"], "method": "clarified"}
        conv.routing = [*(conv.routing or []), record]
        fd = settings.get("front_desk") or {}
        meta: dict[str, Any] = {"routing": {"method": record["method"], "confidence": record["confidence"]},
                                "conversation": {"pipeline": fd.get("pipeline")},
                                "handoff": {"reason": "", "summary": "", "routed": True}}
        if fd.get("persona_id"):
            meta["live"] = {"persona_id": fd["persona_id"]}  # one voice for the whole conversation
        for key in ("admission", "telephony"):
            if settings.get(key):
                meta[key] = settings[key]
        call = await start_segment(s, conv, record["agent_id"], record["method"], app, context=settings.get("context") or None,
                                   identification=settings.get("identification"), meta=meta)
        version = await s.get(AgentVersion, call.agent_version_id)
        agent = await s.get(Agent, call.agent_id)
        intro = intro_line(version.config if version else {}, agent.name if agent else "")
        for seq, e in enumerate(events, 1):  # the front desk's lines open the segment's transcript
            s.add(CallEvent(tenant_id=tenant_id, call_id=call.id, seq=seq, kind=e["kind"], text=e["text"], data={"front_desk": True}))
        await s.commit()
        call_id, agent_id = call.id, call.agent_id
    session = await AgentSession.open(call_id, tenant_id, app=app)
    session.intro_pending = intro
    bus.publish(tenant_id, topic, "routing.decision", {"conversation_id": conv_id, "decision": record})
    bus.publish(tenant_id, topic, "conversation.segment",
                {"conversation_id": conv_id, "call_id": call_id, "agent_id": agent_id, "segment": 1, "routed_by": record["method"]})
    return {"kind": "routed", "call_id": call_id, "agent_id": agent_id, "intro": intro, "record": record, "session": session}


async def routed_text_turn(conv_id: str, tenant_id: str, text: str, app: Any) -> dict[str, Any]:
    out = await front_desk_turn(conv_id, tenant_id, text, app)
    if out["kind"] != "routed":
        return await turn_result(conv_id, tenant_id, [{"speaker": "front_desk", "text": out["line"]}], routed=True)
    messages: list[dict[str, Any]] = []
    rest: list[str] = []
    async for chunk in out["session"].respond(text):
        if not messages and chunk == out["intro"]:
            messages.append({"speaker": "agent", "agent_id": out["agent_id"], "text": chunk})
        else:
            rest.append(chunk)
    reply = "".join(rest).strip()
    if reply:
        messages.append({"speaker": "agent", "agent_id": out["agent_id"], "text": reply})
    return await turn_result(conv_id, tenant_id, messages, routed=True)


def _routing_out(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not decision:
        return None
    return {"method": decision.get("method"), "confidence": decision.get("confidence"), "reason": decision.get("reason")}


async def _open_text(conv: Conversation, call: Call, message: str | None, app: Any) -> list[dict[str, Any]]:
    from voiceai.runtime.session import AgentSession

    session = await AgentSession.open(call.id, conv.tenant_id, app=app)
    messages = [{"speaker": "agent", "agent_id": call.agent_id, "text": await session.start()}]
    if message and message.strip():
        reply = await session.reply(message)
        if reply:
            messages.append({"speaker": "agent", "agent_id": call.agent_id, "text": reply})
    return messages


# ---------------------------------------------------------------- turns
async def _current(conv: Conversation) -> Call:
    async with sessionmaker()() as s:
        call = await s.get(Call, conv.current_call_id) if conv.current_call_id else None
    if call is None:
        raise ApiError(409, "conversation_ended", "This conversation has ended")
    return call


def _check_text_turn(conv: Conversation) -> None:
    if conv.channel != "text":
        raise ApiError(409, "wrong_channel", "Messages can only be sent to text conversations")
    if conv.status == "ended":
        raise ApiError(409, "conversation_ended", "This conversation has ended")


async def turn_result(conv_id: str, tenant_id: str, messages: list[dict[str, Any]], routed: bool = False, transferred: bool = False) -> dict[str, Any]:
    async with sessionmaker()() as s:
        conv = await get(s, tenant_id, conv_id)
        current = await s.get(Call, conv.current_call_id) if conv.current_call_id else None
        agent = await s.get(Agent, current.agent_id) if current else None
        return {
            "conversation_id": conv.id, "status": conv.status, "agent": agent_ref(agent),
            "routing": _routing_out((conv.routing or [None])[-1]) if routed else None,
            "messages": messages, "transferred": transferred, "escalation": await _escalation_of(s, conv),
            "ended": conv.status == "ended",
        }


async def message(conv: Conversation, text: str, app: Any) -> dict[str, Any]:
    """PUB-05: one caller turn of a text conversation."""
    from voiceai.runtime.session import AgentSession

    _check_text_turn(conv)
    if not conv.current_call_id:  # still at the front desk
        return await routed_text_turn(conv.id, conv.tenant_id, text, app)
    call = await _current(conv)
    session = await AgentSession.open(call.id, conv.tenant_id, app=app)
    reply = await session.reply(text)
    messages = [{"speaker": "agent", "agent_id": call.agent_id, "text": reply}] if reply else []
    transferred = False
    while session.transferred_to is not None:  # XFR-01: the next agent's intro and answer follow in the same turn
        session, transferred = session.transferred_to, True
        messages += await _answer(session, last_caller_line(session) or text)
    return await turn_result(conv.id, conv.tenant_id, messages, routed=transferred, transferred=transferred)


def last_caller_line(session: Any) -> str | None:  # noqa: ANN401
    return getattr(session, "carried_caller_line", None)


async def _answer(session: Any, text: str) -> list[dict[str, Any]]:  # noqa: ANN401
    """A segment's first answer: its intro (one message) and its reply (another)."""
    intro = session.intro_pending
    out: list[dict[str, Any]] = []
    rest: list[str] = []
    async for chunk in session.respond(text):
        if intro and not out and chunk == intro:
            out.append({"speaker": "agent", "agent_id": session.agent_id, "text": chunk})
        else:
            rest.append(chunk)
    reply = "".join(rest).strip()
    if reply:
        out.append({"speaker": "agent", "agent_id": session.agent_id, "text": reply})
    return out


async def stream_message(conv: Conversation, text: str, app: Any) -> AsyncIterator[str]:
    """PUB-06: the same turn as server-sent events, ending with `turn.done`."""
    from voiceai.runtime.session import AgentSession

    _check_text_turn(conv)
    if not conv.current_call_id:  # the routing turn is answered whole, then streamed one delta per message
        result = await routed_text_turn(conv.id, conv.tenant_id, text, app)
        for m in result["messages"]:
            yield sse("message.delta", m)
        yield sse("turn.done", result)
        return
    call = await _current(conv)
    session = await AgentSession.open(call.id, conv.tenant_id, app=app)
    parts: list[str] = []
    async for chunk in session.respond(text):
        if not chunk:
            continue
        parts.append(chunk)
        yield sse("message.delta", {"speaker": "agent", "agent_id": call.agent_id, "text": chunk})
    reply = "".join(parts).strip()
    messages = [{"speaker": "agent", "agent_id": call.agent_id, "text": reply}] if reply else []
    transferred = False
    while session.transferred_to is not None:
        session, transferred = session.transferred_to, True
        extra = await _answer(session, last_caller_line(session) or text)
        for m in extra:
            yield sse("message.delta", m)
        messages += extra
    yield sse("turn.done", await turn_result(conv.id, conv.tenant_id, messages, routed=transferred, transferred=transferred))


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def end(conv: Conversation, app: Any) -> dict[str, Any]:
    """Idempotent: ends the current segment with reason `hangup` (PUB-05)."""
    from voiceai.runtime.session import AgentSession

    if conv.status != "ended" and not conv.current_call_id:  # ended at the front desk: no segment
        await front_desk_ended(conv.tenant_id, conv.id, "hangup")
    if conv.status != "ended" and conv.current_call_id:
        async with sessionmaker()() as s:
            call = await s.get(Call, conv.current_call_id)
        if call is not None and call.ended_at is None:
            session = await AgentSession.open(call.id, conv.tenant_id, app=app)
            await session.end("hangup")
        else:
            await segment_ended(conv.tenant_id, conv.current_call_id)
    async with sessionmaker()() as s:
        fresh = await get(s, conv.tenant_id, conv.id)
        return {"status": fresh.status, "outcome": fresh.outcome}


MAX_TRANSFERS = 3
CARRIED_STATE = ("verified", "verified_member_ref", "verification_level", "identified_member_ref", "identified_first_name",
                 "verification_attempts")


async def transfer_available(tenant_id: str, conversation_id: str, agent_id: str) -> bool:
    """XFR-03: offered on a conversation segment whose scope has another routable agent."""
    from voiceai.routing import supervisor

    async with sessionmaker()() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv is None or conv.status == "ended":
            return False
        return bool(await supervisor.candidates(s, tenant_id, conv.scope, {agent_id}))


async def transfer(old: Any, requested: dict[str, Any], *, extra_text: str | None = None, allow_clarify: bool = True) -> dict[str, Any]:  # noqa: ANN401
    """The supervisor picks the next agent; a new segment carries verification, context, the reason and summary (XFR-01, XFR-02)."""
    from dataclasses import asdict

    from voiceai.events import bus
    from voiceai.routing import supervisor
    from voiceai.runtime.session import AgentSession

    tenant_id = old.tenant_id
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, old.conversation_id)
        old_call = await s.get(Call, old.call_id)
        if conv is None or old_call is None:
            return {"kind": "escalate", "detail": "The conversation is gone"}
        if conv.transfer_count >= MAX_TRANSFERS:  # XFR-04
            return {"kind": "escalate", "detail": f"The conversation reached {MAX_TRANSFERS} transfers"}
        scope, channel, clarifications = conv.scope, conv.channel, conv.clarifications
    callers = [m["content"] for m in old.history if m.get("role") == "user" and isinstance(m.get("content"), str)]
    last = extra_text or (callers[-1] if callers else "")
    request = " ".join([*callers[-2:], *([extra_text] if extra_text else [])])
    record = await supervisor.route(tenant_id, scope, request or (requested.get("reason") or ""), channel=channel, trigger="transfer",
                                    exclude={old.agent_id}, reason=requested.get("reason"),
                                    clarifications_used=clarifications if allow_clarify else 99, allow_clarify=allow_clarify)
    topic = f"conversation:{old.conversation_id}"
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, old.conversation_id)
        if record["method"] == "clarify":
            conv.clarifications += 1
            conv.routing = [*(conv.routing or []), record]
            await s.commit()
            bus.publish(tenant_id, topic, "routing.decision", {"conversation_id": conv.id, "decision": record})
            return {"kind": "clarify", "line": record["clarification"]}
        if record["agent_id"] is None:  # no candidate: escalate
            conv.routing = [*(conv.routing or []), record]
            await s.commit()
            return {"kind": "escalate", "detail": "No other agent can take this request"}
        old_call = await s.get(Call, old.call_id)
        old_meta = old_call.meta or {}
        settings = old.call_settings
        persona_id = (old_meta.get("live") or {}).get("persona_id") or (settings.persona or {}).get("id")
        conv_meta = dict(old_meta.get("conversation") or {})
        conv_meta.setdefault("pipeline", settings.pipeline)  # one voice and pipeline for the conversation (XFR-06)
        conv_meta.setdefault("realtime_voice", ((settings.config.get("voice") or {}).get("realtime") or {}).get("voice"))
        carried = {k: v for k, v in asdict(old.state).items() if k in CARRIED_STATE}
        history = [m for m in old.history if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"]]
        if history and history[-1]["role"] == "user" and history[-1]["content"] == last:
            history = history[:-1]  # the new segment records the caller's last line itself
        meta: dict[str, Any] = {
            "handoff": {"reason": requested.get("reason") or "", "summary": requested.get("summary") or "", "from_call_id": old.call_id},
            "routing": {"method": record["method"], "confidence": record["confidence"]},
            "conversation": conv_meta, "state": carried, "history": [{"role": m["role"], "content": m["content"]} for m in history[-6:]],
        }
        if persona_id:
            meta["live"] = {"persona_id": persona_id}
        for key in ("admission", "telephony"):
            if old_meta.get(key):
                meta[key] = old_meta[key]
        call = await start_segment(s, conv, record["agent_id"], "transfer", app=old.tools.app, context=old_meta.get("context") or None,
                                   identification=old_meta.get("identification"), meta=meta)
        if carried.get("verified_member_ref"):
            call.caller_ref = carried["verified_member_ref"]
        conv.transfer_count += 1
        conv.routing = [*(conv.routing or []), record]
        version = await s.get(AgentVersion, call.agent_version_id)
        agent = await s.get(Agent, call.agent_id)
        intro = intro_line(version.config if version else {}, agent.name if agent else "")
        segment, new_call_id, new_agent = call.segment, call.id, call.agent_id
        data = {"from_agent_id": old.agent_id, "to_agent_id": new_agent, "segment": segment}
        await webhooks.emit(s, conv, "conversation.transferred", data)
        await s.commit()
    session = await AgentSession.open(new_call_id, tenant_id, app=old.tools.app)
    session.intro_pending = intro
    session.carried_caller_line = last
    if session.state.verified:  # XFR-02: the receiving agent loads its own memory of the member
        await session._on_verified()
    bus.publish(tenant_id, topic, "routing.decision", {"conversation_id": old.conversation_id, "decision": record})
    bus.publish(tenant_id, topic, "conversation.transferred", {"conversation_id": old.conversation_id, "from_call_id": old.call_id,
                                                              "to_call_id": new_call_id, "reason": requested.get("reason"), **data})
    bus.publish(tenant_id, topic, "conversation.segment", {"conversation_id": old.conversation_id, "call_id": new_call_id,
                                                          "agent_id": new_agent, "segment": segment, "routed_by": "transfer"})
    return {"kind": "routed", "session": session}


async def front_desk_ended(tenant_id: str, conv_id: str, reason: str) -> None:
    """A conversation that ends before an agent was chosen has no segment."""
    async with sessionmaker()() as s:
        row = await s.get(Conversation, conv_id)
        if row is None or row.status == "ended" or row.current_call_id:
            return
        row.status, row.end_reason, row.ended_at = "ended", reason, utcnow()
        row.outcome = "abandoned"
        await webhooks.emit(s, row, "conversation.ended", {"status": "ended", "outcome": "abandoned", "end_reason": reason, "segments": []})
        await s.commit()


# ---------------------------------------------------------------- lifecycle hooks (called by the runtime and jobs)
async def segment_ended(tenant_id: str, call_id: str) -> None:
    """A segment ended: the conversation ends with it, unless the conversation moved on to another segment."""
    async with sessionmaker()() as s:
        call = await s.get(Call, call_id)
        if call is None or not call.conversation_id:
            return
        conv = await s.get(Conversation, call.conversation_id)
        if conv is None or conv.status == "ended" or conv.current_call_id != call.id:
            return
        conv.status, conv.outcome, conv.end_reason, conv.ended_at = "ended", call.outcome, call.end_reason, utcnow()
        segments = await _segments(s, conv)
        await webhooks.emit(s, conv, "conversation.ended", {
            "status": conv.status, "outcome": conv.outcome, "end_reason": conv.end_reason,
            "segments": [{"call_id": c.id, "agent_id": c.agent_id, "outcome": c.outcome} for c in segments]})
        await s.commit()
    from voiceai.events import bus

    bus.publish(tenant_id, f"conversation:{conv.id}", "conversation.ended",
                {"conversation_id": conv.id, "status": conv.status, "outcome": conv.outcome, "end_reason": conv.end_reason})


async def segment_escalated(tenant_id: str, call_id: str, escalation_id: str | None, category: str) -> None:
    async with sessionmaker()() as s:
        call = await s.get(Call, call_id)
        if call is None or not call.conversation_id:
            return
        conv = await s.get(Conversation, call.conversation_id)
        if conv is None or conv.status == "ended":
            return
        conv.status = "escalated"
        await webhooks.emit(s, conv, "conversation.escalated", {"escalation_id": escalation_id, "reason_category": category, "agent_id": call.agent_id})
        await s.commit()


async def outcome_changed(s: AsyncSession, call: Call) -> None:
    """The analysis set a segment's outcome after the call ended: the conversation's outcome follows its current segment."""
    if not call.conversation_id:
        return
    conv = await s.get(Conversation, call.conversation_id)
    if conv is not None and conv.current_call_id == call.id and conv.status == "ended":
        conv.outcome = call.outcome


async def segment_scored(s: AsyncSession, call: Call) -> None:
    """`conversation.analyzed` once every segment of an ended conversation has a scorecard (caller commits)."""
    if not call.conversation_id:
        return
    conv = await s.get(Conversation, call.conversation_id)
    if conv is None or conv.status != "ended" or (conv.settings or {}).get("analyzed_sent"):
        return
    segments = await _segments(s, conv)
    cards = {c.call_id: c for c in (await s.scalars(select(CallScorecard).where(CallScorecard.call_id.in_([x.id for x in segments])))).all()}
    if any(x.id not in cards and x.id != call.id for x in segments) or not segments:
        return
    conv.settings = {**(conv.settings or {}), "analyzed_sent": True}
    rows = [{"call_id": x.id, "agent_id": x.agent_id, "outcome": x.outcome,
             "score": cards[x.id].score if x.id in cards else None, "hard_fail": cards[x.id].hard_fail if x.id in cards else None}
            for x in segments]
    await webhooks.emit(s, conv, "conversation.analyzed", {"outcome": conv.outcome, "segments": rows}, transcript=await transcript(s, conv))


async def connected(tenant_id: str, conversation_id: str) -> None:
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, conversation_id)
        if conv is not None and conv.tenant_id == tenant_id:
            conv.settings = {**(conv.settings or {}), "connected_at": utcnow().isoformat()}
            await s.commit()


async def expire_unconnected(tenant_id: str | None = None, now=None) -> int:  # noqa: ANN001
    """A voice conversation whose client never connected within the token lifetime ends `idle` / `abandoned`."""
    from voiceai.runtime.session import AgentSession

    cutoff = (now or utcnow()) - timedelta(seconds=tokens.TTL_S + 5)
    async with sessionmaker()() as s:
        q = select(Conversation).where(Conversation.channel == "voice", Conversation.status != "ended", Conversation.started_at < cutoff)
        if tenant_id:
            q = q.where(Conversation.tenant_id == tenant_id)
        stale = [c for c in (await s.scalars(q)).all() if not (c.settings or {}).get("connected_at")]
    for conv in stale:
        if not conv.current_call_id:
            await front_desk_ended(conv.tenant_id, conv.id, "idle")
            continue
        session = await AgentSession.open(conv.current_call_id, conv.tenant_id)
        await session.end("idle")
        async with sessionmaker()() as s:
            call = await s.get(Call, conv.current_call_id)
            if call is not None and not call.outcome:
                call.outcome = "abandoned"
            row = await s.get(Conversation, conv.id)
            if row is not None:
                row.outcome = row.outcome or "abandoned"
            await s.commit()
    return len(stale)
