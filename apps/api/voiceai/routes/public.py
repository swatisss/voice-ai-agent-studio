"""The public /v1 API: agents, conversations, and the voice and media-stream sockets.

Spec: /api/public-api.md, /architecture/multi-tenancy.md (Tenant resolution), /architecture/webhooks.md
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from pydantic import BaseModel, Field

from voiceai import call_settings, conversations, voice_calls
from voiceai.errors import ApiError
from voiceai.conversations import CreateBody
from voiceai.db import get_session, sessionmaker
from voiceai.models import Call, Conversation
from voiceai.public import tokens
from voiceai.public.auth import Client, api_client
from voiceai.routes.calls import MessageBody

log = logging.getLogger("voiceai.public")
router = APIRouter(prefix="/v1/tenants/{tenant_id}")
sockets = APIRouter(prefix="/v1")


@router.get("/agents")
async def agents(client: Client = Depends(api_client), s: AsyncSession = Depends(get_session)) -> dict:
    """PUB-03: published, routable agents of the key's scope."""
    rows = await conversations.scoped_agents(s, client.tenant_id, client.scope)
    return {"items": [{"id": a.id, "name": a.name, "description": v.config.get("description", a.description or "")} for a, v in rows]}


@router.post("/conversations", status_code=201)
async def create(body: CreateBody, request: Request, client: Client = Depends(api_client), s: AsyncSession = Depends(get_session)) -> dict:
    return await conversations.create(
        s, client.tenant_id, body, source="api", scope=client.scope, app=request.app, api_key_id=client.key.id,
        max_concurrent_voice=client.key.max_concurrent_voice, base_url=str(request.base_url))


@router.post("/conversations/{conversation_id}/messages", response_model=None)
async def message(conversation_id: str, body: MessageBody, request: Request, client: Client = Depends(api_client),
                  s: AsyncSession = Depends(get_session)) -> dict | StreamingResponse:
    conv = await conversations.get(s, client.tenant_id, conversation_id, source="api")
    await s.close()
    if "text/event-stream" in request.headers.get("accept", ""):  # PUB-06
        conversations._check_text_turn(conv)
        return StreamingResponse(conversations.stream_message(conv, body.text, request.app), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await conversations.message(conv, body.text, request.app)


@router.post("/conversations/{conversation_id}/end")
async def end(conversation_id: str, request: Request, client: Client = Depends(api_client), s: AsyncSession = Depends(get_session)) -> dict:
    conv = await conversations.get(s, client.tenant_id, conversation_id, source="api")
    await s.close()
    return await conversations.end(conv, request.app)


@router.get("/conversations/{conversation_id}")
async def detail(conversation_id: str, include: str | None = None, client: Client = Depends(api_client),
                 s: AsyncSession = Depends(get_session)) -> dict:
    conv = await conversations.get(s, client.tenant_id, conversation_id, source="api")
    return await conversations.view(s, conv, include_transcript=include == "transcript")


# ---------------------------------------------------------------- sockets (token-authenticated, PUB-07, PUB-08)
async def _accept(websocket: WebSocket, conversation_id: str, transport: str) -> tuple[Conversation, Call | None] | None:
    """Accept the socket, then check the connect token; close 4401 / 4404 before any pipeline starts."""
    offered = list(websocket.scope.get("subprotocols") or [])
    await websocket.accept(subprotocol=tokens.SUBPROTOCOL if tokens.SUBPROTOCOL in offered else None)
    token = tokens.presented(websocket.headers, offered)
    async with sessionmaker()() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if conv is None or conv.transport != transport or not tokens.consume(conv.tenant_id, conv.id, transport, token):
        await websocket.close(code=4401, reason="bad token")
        return None
    async with sessionmaker()() as s:
        call = await s.get(Call, conv.current_call_id) if conv.current_call_id else None
    if conv.status == "ended" or (conv.current_call_id and (call is None or call.ended_at)):
        await websocket.close(code=4404, reason="unknown or ended conversation")
        return None
    await conversations.connected(conv.tenant_id, conv.id)
    return conv, call


@sockets.websocket("/voice/{conversation_id}")
async def voice(websocket: WebSocket, conversation_id: str) -> None:
    accepted = await _accept(websocket, conversation_id, "websocket")
    if accepted:
        conv, _call = accepted
        await voice_calls.serve_conversation(websocket, conv)  # front desk first when routed; transfers keep the socket


@sockets.websocket("/media-stream/{conversation_id}")
async def media_stream(websocket: WebSocket, conversation_id: str) -> None:
    """Twilio Media Streams frames from any carrier, in μ-law 8 kHz or PCM 16 kHz (PUB-08)."""
    from voiceai.voice.phone import PhoneStream, read_start

    accepted = await _accept(websocket, conversation_id, "media-stream")
    if not accepted:
        return
    conv, call = accepted
    start = await read_start(websocket)
    if not start:
        await websocket.close(code=1000)
        return
    phone = PhoneStream(call_sid=str(start.get("callSid") or ""), stream_sid=str(start.get("streamSid") or ""),
                        parameters=dict(start.get("customParameters") or {}),
                        audio_format=(conv.settings or {}).get("audio_format", "mulaw_8k"), twilio=False)
    await voice_calls.serve_conversation(websocket, conv, phone)
    if websocket.client_state != WebSocketState.DISCONNECTED and websocket.application_state != WebSocketState.DISCONNECTED:
        await websocket.close(code=1000)


class Offer(BaseModel):
    sdp: str = Field(min_length=10, max_length=200_000)
    type: str = "offer"


@sockets.post("/webrtc/{conversation_id}/offer")
async def webrtc_offer(conversation_id: str, body: Offer, request: Request) -> dict:
    """WRTC-01, WRTC-02: the SDP answer for a WebRTC conversation; the token is single-use, like the voice socket's."""
    from voiceai import admission
    from voiceai.public import webrtc

    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    async with sessionmaker()() as s:
        conv = await s.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if conv is None or conv.transport != "webrtc" or not tokens.consume(conv.tenant_id, conv.id, "webrtc", token):
        raise ApiError(401, "invalid_token", "Send the conversation's connect token as Authorization: Bearer <token>")
    if conv.status == "ended":
        raise ApiError(404, "conversation_not_found", "Conversation not found")
    if not webrtc.available():
        raise ApiError(503, "webrtc_unavailable", "WebRTC needs a TURN relay on this server")
    async with sessionmaker()() as s:
        current = await s.get(Call, conv.current_call_id) if conv.current_call_id else None
        config = (await call_settings.load(s, current)).config if current else await conversations.front_desk_config(s, conv)
        planned = (current.meta or {}).get("admission") if current else (conv.settings or {}).get("admission")
        decided = await admission.admit_socket(s, conv.tenant_id, config, planned)
    if isinstance(decided, admission.Refusal):
        raise ApiError(409, decided.reason, "Voice is not available right now")
    await conversations.connected(conv.tenant_id, conv.id)
    return await webrtc.answer(conv, body.sdp, body.type)


def request_id_middleware(app) -> None:  # noqa: ANN001
    """`X-Request-Id` echoed on /v1 (generated when absent) and logged with the key prefix, never the key."""
    from voiceai.db import new_id

    @app.middleware("http")
    async def _request_id(request: Request, call_next):  # noqa: ANN001, ANN202
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)
        rid = request.headers.get("x-request-id") or new_id()
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        log.info("v1 %s %s %s key=%s id=%s", request.method, request.url.path, response.status_code,
                 getattr(request.state, "key_prefix", "-"), rid)
        return response


__all__ = ["router", "sockets", "request_id_middleware", "JSONResponse"]
