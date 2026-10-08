"""The voice WebSocket: one browser audio session bound to one call.

Spec: /api/voice-protocol.md, /architecture/voice-pipeline.md

Pipecat is imported lazily inside the handler so that a deployment without it - a worker image, or
anyone running `voiceai seed` - still starts, and so that the socket can answer VO-05 cleanly.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket
from sqlalchemy import select

from voiceai.core.config import get_settings
from voiceai.core.db import sessionmaker
from voiceai.core.errors import ApiError
from voiceai.core.tables import Call
from voiceai.core.tenancy import resolve_tenant
from voiceai.core.toolcalling import tool_caller
from voiceai.modules.conversation.contract import open_session
from voiceai.modules.voice.controls import LIVE, LiveControls

log = logging.getLogger("voiceai.voice")
router = APIRouter(prefix="/api")


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
        from voiceai.modules.voice import pipeline
    except Exception as exc:  # noqa: BLE001
        log.error("voice pipeline unavailable: %s", exc)
        await websocket.close(code=4500, reason="voice_unavailable")
        return
    session = await open_session(call_id, tenant_id, caller=tool_caller(websocket.app))
    controls = LiveControls(turn=session.turn_settings())
    LIVE[call_id] = controls
    try:
        await pipeline.run(websocket, session, key, controls)
    finally:
        LIVE.pop(call_id, None)
