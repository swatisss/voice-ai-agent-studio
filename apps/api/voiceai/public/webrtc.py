"""WebRTC for conversations: ICE servers (STUN, TURN on Cloud Run) and the SDP offer/answer behind a connect token.

Spec: /architecture/webrtc-transport.md, /api/public-api.md (Voice connect)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from voiceai.config import get_settings

log = logging.getLogger("voiceai.webrtc")
_running: set[asyncio.Task[Any]] = set()


def _urls(raw: str | None) -> list[str]:
    return [u.strip() for u in (raw or "").split(",") if u.strip()]


def available() -> bool:
    """WRTC-03: on Cloud Run (no inbound UDP) WebRTC needs a TURN relay."""
    return bool(_urls(get_settings().webrtc_turn_urls)) or not os.environ.get("K_SERVICE")


def ice_servers() -> list[dict[str, Any]]:
    """What the client gets: STUN, and TURN with its credential when configured."""
    s = get_settings()
    servers: list[dict[str, Any]] = [{"urls": u} for u in _urls(s.webrtc_stun_urls)]
    turn = _urls(s.webrtc_turn_urls)
    if turn:
        servers.append({"urls": turn, "username": s.webrtc_turn_username or "", "credential": s.webrtc_turn_credential or ""})
    return servers


def server_ice() -> list[Any]:
    """The same servers in Pipecat's (aiortc's) form, for the server side of the peer connection."""
    from pipecat.transports.smallwebrtc.connection import IceServer

    out = []
    for entry in ice_servers():
        for url in entry["urls"] if isinstance(entry["urls"], list) else [entry["urls"]]:
            out.append(IceServer(urls=url, username=entry.get("username") or None, credential=entry.get("credential") or None))
    return out


async def answer(conv: Any, sdp: str, kind: str) -> dict[str, Any]:  # noqa: ANN401
    """Create the server's peer connection for the offer and start the conversation on it (WRTC-01)."""
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

    from voiceai import voice_calls

    conn = SmallWebRTCConnection(ice_servers=server_ice())
    await conn.initialize(sdp=sdp, type=kind)
    result = conn.get_answer() or {}
    task = asyncio.ensure_future(voice_calls.serve_conversation(conn, conv))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return {"sdp": result.get("sdp"), "type": result.get("type", "answer")}
