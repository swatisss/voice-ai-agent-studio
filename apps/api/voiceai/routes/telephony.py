"""Twilio voice webhook and Media Stream WebSocket.

Spec: /architecture/telephony.md, /api/rest-api.md (Phone numbers and telephony), /architecture/multi-tenancy.md,
/architecture/tenant-settings.md, /architecture/call-admission.md, /architecture/supervisor-routing.md (Phone numbers)
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Request, Response, WebSocket
from sqlalchemy import select
from starlette.websockets import WebSocketState

from voiceai import telephony
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.errors import ApiError
from voiceai import admission, caller_id, voice_calls
from voiceai.models import Agent, AgentVersion, Call, Conversation, PhoneNumber
from voiceai.runtime.session import create_call

log = logging.getLogger("voiceai.telephony")
router = APIRouter(prefix="/api/telephony/twilio")


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
    attestation = (params.get("StirVerstat") or [""])[0] or None
    match = await caller_id.identify(caller, request.app)  # IDV-01: before the call exists; the number itself is never stored

    async with sessionmaker()() as db:
        number = await db.scalar(select(PhoneNumber).where(PhoneNumber.e164 == dialled))
        if number is not None and number.target == "front_desk":  # TEL-12: the supervisor picks the agent
            context = telephony.ivr_context({**dict(request.query_params), **{k: v for k, v in params.items()}})
            conv_id = await _front_desk_conversation(db, number.tenant_id, request, call_sid, caller, dialled, context,
                                                     caller_id.identification(match, attestation) if match else None)
            if conv_id is None:
                return _xml(telephony.twiml_not_in_service())
            token = telephony.mint_token(s.twilio_auth_token, conv_id)
            return _xml(telephony.twiml_stream(telephony.stream_url(conv_id, token, kind="conversation"), conv_id))
        agent = await db.scalar(select(Agent).where(Agent.id == number.agent_id, Agent.tenant_id == number.tenant_id)) if number else None
        version = await db.get(AgentVersion, agent.published_version_id) if agent and agent.published_version_id else None
        if not version or version.config.get("mode") == "outbound":  # TEL-03: unmapped, unpublished or not an answering agent
            return _xml(telephony.twiml_not_in_service())
        call = await create_call(db, number.tenant_id, agent.id, "voice", app=request.app)
        decided = await voice_calls.admit(db, number.tenant_id, call)  # ADM-05: the stream uses this plan's credential source
        if isinstance(decided, admission.Refusal):  # TEL-03, MT-08, ADM-03: rolled back, no call row is kept
            await db.rollback()
            return _xml(telephony.twiml_not_in_service())
        context = telephony.ivr_context({**dict(request.query_params), **{k: v for k, v in params.items()}})  # TEL-05
        meta = dict(call.meta or {})
        meta["telephony"] = {
            "provider": "twilio", "call_sid": call_sid, "from_last4": re.sub(r"\D", "", caller)[-4:], "to": dialled,
        }
        if context:
            meta["context"] = context
        if match:
            meta["identification"] = caller_id.identification(match, attestation)
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
    phone = PhoneStream(call_sid=call_sid, stream_sid=str(start.get("streamSid") or ""), parameters=dict(start.get("customParameters") or {}))
    await voice_calls.serve(websocket, call.tenant_id, call, phone)
    if websocket.client_state != WebSocketState.DISCONNECTED and websocket.application_state != WebSocketState.DISCONNECTED:
        await websocket.close(code=1000)  # TEL-11: a call that ended closes its stream normally, so Twilio moves on to <Hangup/>


async def _front_desk_conversation(db, tenant_id: str, request: Request, call_sid: str, caller: str, dialled: str,  # noqa: ANN001
                                   context: dict, identification: dict | None) -> str | None:
    """A phone conversation (scope member) answered by the front desk; None = not in service (TEL-12)."""
    from voiceai import conversations
    from voiceai.routing import supervisor

    if not await supervisor.candidates(db, tenant_id, "member"):
        return None
    conv = Conversation(tenant_id=tenant_id, source="phone", channel="voice", transport="twilio", scope="member", settings={})
    db.add(conv)
    await db.flush()
    telephony_meta = {"provider": "twilio", "call_sid": call_sid, "from_last4": re.sub(r"\D", "", caller)[-4:], "to": dialled}
    await conversations.open_front_desk(db, conv, context=context, identification=identification, extra={"telephony": telephony_meta})
    decided = await admission.admit(db, tenant_id, await conversations.front_desk_config(db, conv))
    if isinstance(decided, admission.Refusal):
        await db.rollback()
        return None
    conv.settings = {**conv.settings, "admission": decided.to_meta()}
    await db.commit()
    return conv.id


@router.websocket("/conversation/{conversation_id}")
async def conversation_stream(websocket: WebSocket, conversation_id: str) -> None:
    """TEL-12: the Media Stream of a call to a front-desk number."""
    from voiceai.voice.phone import PhoneStream, read_start

    await websocket.accept()
    s = get_settings()
    if not (s.twilio_auth_token and telephony.consume_token(s.twilio_auth_token, conversation_id, websocket.query_params.get("token"))):
        await websocket.close(code=4401, reason="bad token")
        return
    async with sessionmaker()() as db:
        conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.status == "ended":
        await websocket.close(code=4404, reason="unknown or ended conversation")
        return
    start = await read_start(websocket)
    if not start:
        await websocket.close(code=1000)
        return
    from voiceai import conversations

    await conversations.connected(conv.tenant_id, conv.id)
    phone = PhoneStream(call_sid=str(start.get("callSid") or ""), stream_sid=str(start.get("streamSid") or ""), parameters=dict(start.get("customParameters") or {}))
    await voice_calls.serve_conversation(websocket, conv, phone)
    if websocket.client_state != WebSocketState.DISCONNECTED and websocket.application_state != WebSocketState.DISCONNECTED:
        await websocket.close(code=1000)
