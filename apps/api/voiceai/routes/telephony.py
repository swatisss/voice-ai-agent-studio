"""Twilio voice webhook and Media Stream WebSocket.

Spec: /architecture/telephony.md, /api/rest-api.md (Phone numbers and telephony), /architecture/multi-tenancy.md
"""
from __future__ import annotations

import functools
import logging
import re

from fastapi import APIRouter, Depends, Request, Response, WebSocket
from pydantic import BaseModel
from sqlalchemy import select
from starlette.websockets import WebSocketState

from voiceai import telephony
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.errors import ApiError
from voiceai.live import pipeline_of
from voiceai.llm.gateway import gateway
from voiceai.models import Agent, AgentVersion, Call, PhoneNumber
from voiceai.routes.calls import serve_voice
from voiceai.runtime.session import create_call
from voiceai.schemas import E164_RE
from voiceai.tenancy import current_tenant

log = logging.getLogger("voiceai.telephony")
router = APIRouter(prefix="/api/telephony/twilio")
phone_router = APIRouter(prefix="/api/phone")


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


@router.post("/voice")
async def voice_webhook(request: Request) -> Response:
    """TEL-01, TEL-02, TEL-03, TEL-05, TEL-10: answer a Twilio call with TwiML that connects its audio to the stream."""
    s = get_settings()
    form = await request.form()
    params = {key: [str(v) for v in form.getlist(key)] for key in form.keys()}
    if not (s.twilio_auth_token and s.public_base_url):  # TEL-10: not configured
        return _xml(telephony.twiml_not_in_service())
    if s.twilio_validate_signature:  # TEL-02
        query = request.url.query
        url = telephony.public_url(request.url.path + (f"?{query}" if query else ""))
        if not telephony.valid_signature(s.twilio_auth_token, url, params, request.headers.get("x-twilio-signature")):
            raise ApiError(403, "invalid_signature", "Bad or missing X-Twilio-Signature")
    dialled = (params.get("To") or [""])[0].strip()
    caller = (params.get("From") or [""])[0]
    call_sid = (params.get("CallSid") or [""])[0]

    async with sessionmaker()() as db:
        number = await db.scalar(select(PhoneNumber).where(PhoneNumber.e164 == dialled))
        agent = await db.scalar(select(Agent).where(Agent.id == number.agent_id, Agent.tenant_id == number.tenant_id)) if number else None
        version = await db.get(AgentVersion, agent.published_version_id) if agent and agent.published_version_id else None
        if not version or version.config.get("mode") == "outbound":  # TEL-03: unmapped, unpublished or not an answering agent
            return _xml(telephony.twiml_not_in_service())
        realtime = pipeline_of(version.config) == "realtime"
        if not (gateway().provider_key("openai") if realtime else s.deepgram_api_key):  # TEL-03: the pipeline has no key
            return _xml(telephony.twiml_not_in_service())
        call = await create_call(db, number.tenant_id, agent.id, "voice", app=request.app)
        context = telephony.ivr_context({**dict(request.query_params), **{k: v for k, v in params.items()}})  # TEL-05
        meta = dict(call.meta or {})
        meta["telephony"] = {
            "provider": "twilio", "call_sid": call_sid, "from_last4": re.sub(r"\D", "", caller)[-4:], "to": dialled,
        }
        if context:
            meta["context"] = context
        call.meta = meta
        await db.commit()
        call_id = call.id
    token = telephony.mint_token(s.twilio_auth_token, call_id)
    return _xml(telephony.twiml_stream(telephony.stream_url(call_id, token), call_id))


@router.websocket("/stream/{call_id}")
async def stream(websocket: WebSocket, call_id: str) -> None:
    """TEL-04, TEL-06, TEL-11: the Twilio Media Stream of one call; runs the same pipelines as a browser call."""
    from voiceai.voice.phone import PhoneStream, read_start

    await websocket.accept()
    s = get_settings()
    if not (s.twilio_auth_token and telephony.consume_token(s.twilio_auth_token, call_id, websocket.query_params.get("token"))):
        await websocket.close(code=4401, reason="bad token")
        return
    async with sessionmaker()() as db:
        call = await db.scalar(select(Call).where(Call.id == call_id))
    if not call or call.ended_at or call.channel != "voice":
        await websocket.close(code=4404, reason="unknown or ended call")
        return
    start = await read_start(websocket)
    if not start:
        await websocket.close(code=1000)
        return
    call_sid = str(start.get("callSid") or ((call.meta or {}).get("telephony") or {}).get("call_sid") or "")
    phone = PhoneStream(
        call_sid=call_sid, stream_sid=str(start.get("streamSid") or ""), parameters=dict(start.get("customParameters") or {}),
        on_end=functools.partial(_on_end, call_sid=call_sid),
    )
    await serve_voice(websocket, call.tenant_id, call, phone)
    if websocket.client_state != WebSocketState.DISCONNECTED and websocket.application_state != WebSocketState.DISCONNECTED:
        await websocket.close(code=1000)  # TEL-11: a call that ended closes its stream normally, so Twilio moves on to <Hangup/>


async def _on_end(session, reason: str, call_sid: str) -> None:  # noqa: ANN001
    await telephony.on_phone_end(session, reason, call_sid)


class OutboundIn(BaseModel):
    agent_id: str
    member_ref: str
    to: str


@phone_router.post("/outbound")
async def place_outbound(body: OutboundIn, request: Request, tenant_id: str = Depends(current_tenant)) -> dict:
    """TEL-12, TEL-13, TEL-14: an outbound agent phones `to` through Twilio's REST API (or the simulator)."""
    s = get_settings()
    to = body.to.strip()
    if not E164_RE.fullmatch(to):
        raise ApiError(422, "invalid_number", "to must be an international number such as +15551234567")
    if not (s.twilio_account_sid and s.twilio_auth_token and s.public_base_url and s.twilio_phone_number):
        raise ApiError(409, "telephony_not_configured", "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, PUBLIC_BASE_URL and TWILIO_PHONE_NUMBER")
    async with sessionmaker()() as db:
        agent = await db.scalar(select(Agent).where(Agent.id == body.agent_id, Agent.tenant_id == tenant_id))
        if agent is None:
            raise ApiError(404, "agent_not_found", "Agent not found")
        version = await db.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None
        if version is None:
            raise ApiError(409, "agent_not_published", "Publish the agent before calling")
        if version.config.get("mode") != "outbound":
            raise ApiError(409, "not_outbound", "Only outbound agents place calls")
        call = await create_call(db, tenant_id, agent.id, "voice", context={"member_ref": body.member_ref}, app=request.app)
        meta = dict(call.meta or {})
        meta["telephony"] = {"provider": "twilio", "call_sid": "", "to_last4": re.sub(r"\D", "", to)[-4:], "from": s.twilio_phone_number, "direction": "outbound"}
        call.meta = meta
        await db.commit()
        call_id = call.id
    token = telephony.mint_token(s.twilio_auth_token, call_id)
    try:
        sid = await telephony.place_call(to, s.twilio_phone_number, telephony.twiml_stream(telephony.stream_url(call_id, token), call_id))
    except telephony.TwilioError as exc:
        await telephony.close_unanswered(call_id, "error")
        raise ApiError(502, "twilio_error", str(exc)) from exc
    async with sessionmaker()() as db:
        row = await db.get(Call, call_id)
        row.meta = {**(row.meta or {}), "telephony": {**row.meta["telephony"], "call_sid": sid}}
        await db.commit()
    telephony.expire_unanswered(call_id, s.outbound_ring_timeout_s)
    return {"call_id": call_id, "call_sid": sid, "status": "ringing"}
