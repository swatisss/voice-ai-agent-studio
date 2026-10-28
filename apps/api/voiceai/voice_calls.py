"""Voice calls: admitting a new call and serving its audio socket, for the browser and the phone alike.

Spec: /architecture/call-admission.md, /architecture/realtime-voice.md, /architecture/telephony.md, /api/voice-protocol.md

The routes only translate HTTP, TwiML and WebSockets; what a voice call needs before and while it runs lives here.
Pipecat stays inside `voiceai/voice/` and is imported only when a socket is served.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import admission, call_settings
from voiceai.db import sessionmaker
from voiceai.live import LiveControls, follow
from voiceai.models import Call
from voiceai.runtime.session import AgentSession

log = logging.getLogger("voiceai.voice_calls")


async def admit(s: AsyncSession, tenant_id: str, call: Call) -> admission.CallPlan | admission.Refusal:
    """ADM-01, ADM-05: decide whether a new voice call may start and record its plan on the call (not committed).
    On a refusal the caller rolls back, so no call row is kept (ADM-02, ADM-03)."""
    decided = await admission.admit(s, tenant_id, (await call_settings.load(s, call)).config)
    if isinstance(decided, admission.CallPlan):
        call.meta = {**(call.meta or {}), "admission": decided.to_meta()}
    return decided


async def serve(websocket: WebSocket, tenant_id: str, call: Call, phone: Any | None = None) -> None:  # noqa: ANN401
    """Run the voice pipeline the call's agent version asks for, on a socket that is already accepted.

    Close 4500 when the pipeline's provider is unavailable (VO-05 for the cascade, RV-03 and RV-13 for the realtime
    pipeline).
    """
    async with sessionmaker()() as s:
        config = (await call_settings.load(s, call)).config
        decided = await admission.admit_socket(s, tenant_id, config, (call.meta or {}).get("admission"))
        if isinstance(decided, admission.Refusal):  # MT-08, VO-05, RV-03, ADM-04
            await websocket.close(code=4500, reason=decided.reason)
            return
        plan, key = decided
        if not (call.meta or {}).get("admission"):  # a call created before admission existed: record its plan now
            row = await s.get(Call, call.id)
            if row is not None:
                row.meta = {**(row.meta or {}), "admission": plan.to_meta()}
                await s.commit()
    try:
        from voiceai.voice import pipeline
        from voiceai.voice import realtime as rt
    except Exception as exc:  # noqa: BLE001
        log.error("voice pipeline unavailable: %s", exc)
        await websocket.close(code=4500, reason="voice_unavailable")
        return
    session = await AgentSession.open(call.id, tenant_id, app=websocket.app)
    controls = LiveControls(turn=session.turn_settings())
    unfollow = follow(session, controls)  # live changes reach the pipeline through the session (TD-09)
    try:
        if plan.pipeline == "realtime":
            ref = plan.model_ref or session.call_settings.speech_ref()

            async def connector() -> rt.RealtimeConnection:
                return await rt.connect_openai(key, ref)

            try:
                await pipeline.run_realtime(websocket, session, controls, connector, phone)
            except rt.ProviderUnavailable as exc:  # RV-13
                log.warning("realtime provider unavailable: %s", exc)
                await websocket.close(code=4500, reason="voice_unavailable")
        else:
            await pipeline.run(websocket, session, key, controls, phone)
    finally:
        unfollow()
