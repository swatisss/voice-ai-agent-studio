"""Hosted media room: room names, access tokens, admission, and the live voice handover.

Spec: /architecture/hosted-media-room.md, /decisions/adr-0015-hosted-media-room-livekit.md, /architecture/escalation.md,
/architecture/call-ending-and-feedback.md, /api/rest-api.md

This module has no LiveKit or Pipecat import. Tokens are signed here (a LiveKit access token is an HS256 JWT), and everything
that touches the network goes through a `RoomBackend`; the real one lives in `voiceai/voice/livekit_transport.py` and is
imported only when a room call starts. Tests install a fake backend, so no account, network or secret is involved (LKH-14).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus, caller_partial
from voiceai.models import Call, Escalation

log = logging.getLogger("voiceai.media_room")

CONTROL_TOPIC = "echo.control"
AI_JOIN_TIMEOUT_S = 10.0
AI_LEAVE_TIMEOUT_S = 10.0
INTRO_LINE = "I'm bringing in {name}, who has the details of your request."
ROOM_ENDINGS = ("human_ended", "handover_timeout")

# What each participant's token may do (LKH-02, spec table "Participants"): the secret never leaves this module.
GRANTS: dict[str, dict[str, Any]] = {
    "customer": {"canPublish": True, "canPublishSources": ["microphone"], "canSubscribe": True, "canPublishData": False},
    "ai": {"canPublish": True, "canSubscribe": True, "canPublishData": True},
    "specialist": {"canPublish": True, "canPublishSources": ["microphone"], "canSubscribe": True, "canPublishData": True},
    "scribe": {"canPublish": False, "canSubscribe": True, "canPublishData": False},
}
PREFIX = {"customer": "cust-", "ai": "ai-", "specialist": "spec-", "scribe": "scribe-"}


class RoomUnavailable(Exception):
    """LiveKit refused or could not be reached (LKH-13)."""


# ---------------------------------------------------------------- configuration and tokens
def configured() -> bool:
    """LKH-01, LKH-21: all three settings present; no network call."""
    s = get_settings()
    return bool(s.livekit_url and s.livekit_api_key and s.livekit_api_secret)


def require_configured() -> None:
    if not configured():
        raise ApiError(503, "livekit_unavailable", "Live voice rooms are not configured on this server")


def room_name(call_id: str) -> str:
    return f"lk-{call_id}"


def identity_for(role: str, call_id: str | None = None) -> str:
    """Opaque, no personal data: a random suffix, or the call id for the two server-side participants."""
    if role in ("ai", "scribe") and call_id:
        return f"{PREFIX[role]}{call_id}"
    return f"{PREFIX[role]}{secrets.token_hex(6)}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(role: str, room: str, identity: str, name: str | None = None, ttl_s: int | None = None, now: float | None = None) -> dict[str, Any]:
    """A LiveKit access token for one participant of one room (LKH-02). Returns `{token, identity, expires_at}`."""
    s = get_settings()
    if not (s.livekit_api_key and s.livekit_api_secret):
        raise ApiError(503, "livekit_unavailable", "Live voice rooms are not configured on this server")
    issued = int(now if now is not None else time.time())
    ttl = min(int(ttl_s or s.livekit_token_ttl_s), int(s.livekit_token_ttl_s))
    exp = issued + max(ttl, 1)
    video = {"room": room, "roomJoin": True, "roomAdmin": False, **GRANTS[role]}
    claims: dict[str, Any] = {"iss": s.livekit_api_key, "sub": identity, "nbf": issued, "iat": issued, "exp": exp, "video": video}
    if name:
        claims["name"] = name
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(s.livekit_api_secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return {"token": f"{head}.{body}.{_b64(sig)}", "identity": identity,
            "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()}


def decode(token: str) -> dict[str, Any]:
    """Verify and read a token (tests and the connectivity check); raises ValueError when it does not verify."""
    s = get_settings()
    head, body, sig = token.split(".")
    want = hmac.new((s.livekit_api_secret or "").encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(want, _unb64(sig)):
        raise ValueError("bad signature")
    return json.loads(_unb64(body))


def connect_info(role: str, room: str, name: str | None = None, call_id: str | None = None) -> dict[str, Any]:
    """`{url, token, room, expires_at}`: what a browser needs to join (returned once, never stored)."""
    minted = mint(role, room, identity_for(role, call_id), name)
    return {"url": get_settings().livekit_url, "token": minted["token"], "room": room, "expires_at": minted["expires_at"]}


# ---------------------------------------------------------------- the network seam
class RoomBackend(Protocol):
    """Everything that needs LiveKit. The hub calls it; room events come back through the `participant_*` and
    `transcript` functions below."""

    async def start_ai(self, state: RoomState, session: Any) -> None:  # noqa: ANN401
        """Join as the AI and run the voice pipeline; return once joined, raise `RoomUnavailable` otherwise."""

    async def say(self, call_id: str, text: str) -> None:
        """The AI speaks one fixed line and returns when it has been spoken."""

    async def stop_ai(self, call_id: str) -> None: ...

    async def start_scribe(self, state: RoomState) -> None:
        """Join subscribe-only and transcribe each remote audio track (calls `transcript`)."""

    async def send(self, room: str, message: dict[str, Any]) -> None:
        """A control message to the room's browsers (topic `echo.control`)."""

    async def close_room(self, room: str) -> None: ...


_backend: RoomBackend | None = None


def set_backend(backend: RoomBackend | None) -> None:
    global _backend
    _backend = backend


def backend() -> RoomBackend:
    global _backend
    if _backend is None:
        from voiceai.voice.livekit_transport import LiveKitBackend  # lazy: the SDK is imported only when a room call starts

        _backend = LiveKitBackend()
    return _backend


# ---------------------------------------------------------------- the hub: one RoomState per live call
@dataclass(eq=False)
class RoomState:
    call_id: str
    tenant_id: str
    room: str
    session: Any
    ai_present: bool = True
    voice_state: str | None = None           # None until the call escalates, then waiting | connected | ended
    specialist: str | None = None            # display name of the specialist who took the call
    specialist_identity: str | None = None
    ended: bool = False
    scribe_started: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)


ROOMS: dict[str, RoomState] = {}
_tasks: set[asyncio.Task[None]] = set()


def _spawn(coro: Any) -> asyncio.Task[None]:  # noqa: ANN401
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def in_room(call_id: str) -> bool:
    return call_id in ROOMS


async def settle() -> None:
    """Await background work started by the hub (tests, shutdown)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def first_name(name: str | None) -> str:
    return ((name or "").split() or ["your specialist"])[0]


async def open_call(session: Any) -> dict[str, Any]:  # noqa: ANN401
    """LKH-01, LKH-03: after the call row is committed. Registers the room, starts the AI's join in the background and
    returns the customer's `connect`. The AI speaks the welcome when the customer's microphone connects."""
    call_id, tenant_id = session.call_id, session.tenant_id
    room = room_name(call_id)
    connect = connect_info("customer", room)
    state = RoomState(call_id, tenant_id, room, session)
    ROOMS[call_id] = state
    state.tasks["join"] = _spawn(_join_ai(state))
    state.tasks["max"] = _spawn(_max_clock(state))
    return connect


async def _join_ai(state: RoomState) -> None:
    try:
        await asyncio.wait_for(backend().start_ai(state, state.session), AI_JOIN_TIMEOUT_S)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - LKH-13: timeout, LiveKit refused (plan caps), or media blocked
        log.warning("AI could not join room %s: %s", state.room, type(exc).__name__)
        await end_call(state, "error")


async def _max_clock(state: RoomState) -> None:
    """LKH-18: `max_duration` still applies once the AI has gone quiet or left (before that the pipeline's own clock speaks it)."""
    await asyncio.sleep(float((state.session.config.get("policy") or {}).get("max_call_seconds", 900)))
    if state.voice_state is not None and not state.ended:
        await end_call(state, "max_duration")


async def _wait_clock(state: RoomState) -> None:
    await asyncio.sleep(float(get_settings().handover_wait_s))
    if state.voice_state == "waiting" and not state.ended:
        await end_call(state, "handover_timeout")  # LKH-06: the escalation itself stays waiting for a callback


def _restart_clock(state: RoomState) -> None:
    old = state.tasks.pop("wait", None)
    if old:
        old.cancel()
    state.tasks["wait"] = _spawn(_wait_clock(state))


async def _send(state: RoomState, message: dict[str, Any]) -> None:
    try:
        await backend().send(state.room, message)
    except Exception as exc:  # noqa: BLE001 - a control message never breaks the call
        log.warning("control message not delivered in %s: %s", state.room, type(exc).__name__)


async def _set_voice(state: RoomState, voice_state: str, joined: bool = False) -> None:
    """Record `voice_state` on the escalation and tell the console (LKH-05)."""
    state.voice_state = voice_state
    esc_id = state.session.state.escalation_id
    if not esc_id:
        return
    from voiceai.runtime import escalation as esc_mod

    async with sessionmaker()() as s:
        esc = await s.get(Escalation, esc_id)
        if esc is None:
            return
        esc.voice_state = voice_state
        if joined:
            esc.voice_joined_at = utcnow()
        await s.commit()
        data = esc_mod.summary(esc)
    bus.publish(state.tenant_id, "console", "escalation.updated", {**data, "voice": voice_state})


async def on_handoff(session: Any) -> bool:  # noqa: ANN401
    """LKH-05, LKH-17: the escalated call stays open. Called by `AgentSession.end("handoff")` for a call in a room.
    Returns True when the call was kept open."""
    state = ROOMS.get(session.call_id)
    if state is None or state.ended:
        return False
    if state.voice_state is not None:  # a second hand-off line (idempotent)
        return True
    session.room_silent = True  # no model request on customer speech from now on
    await session._persist()  # noqa: SLF001
    await _set_voice(state, "waiting")
    await _send(state, {"type": "handover", "state": "waiting"})
    _restart_clock(state)
    if not state.scribe_started:
        state.scribe_started = True
        try:
            await backend().start_scribe(state)
        except Exception as exc:  # noqa: BLE001 - the handover still works without a transcript
            log.warning("scribe did not start in %s: %s", state.room, type(exc).__name__)
    return True


async def specialist_join(s: AsyncSession, tenant_id: str, escalation_id: str, actor: str) -> dict[str, Any]:
    """LKH-07: accept the voice escalation for `actor` and return the specialist's `connect`."""
    from voiceai.runtime import escalation as esc_mod

    esc = await esc_mod.get_owned(s, tenant_id, escalation_id)
    call = await s.get(Call, esc.call_id)
    if call is None or not call.media_room:
        raise ApiError(409, "not_voice", "This escalation has no live voice room")
    if call.ended_at is not None or esc.voice_state != "waiting":
        raise ApiError(409, "not_waiting", "The customer is no longer waiting on this call")
    mine = (esc.assignee or "") == (actor or "Specialist")[:120] and esc.voice_joined_at is not None  # reconnecting after a drop
    if esc.status == "accepted" and not mine:
        raise ApiError(409, "already_taken", "Another specialist has taken this call")
    require_configured()
    if esc.status == "waiting":
        esc = await esc_mod.accept(s, tenant_id, escalation_id, actor)
    out = connect_info("specialist", call.media_room, name=actor)
    state = ROOMS.get(call.id)
    if state is not None:
        state.specialist = esc.assignee or actor
    return out


def voice_status(esc: Escalation, call: Call) -> dict[str, Any]:
    """GET /api/escalations/{id}/voice (API table)."""
    if not call.media_room:
        raise ApiError(404, "no_voice_room", "This escalation has no live voice room")
    return {"state": esc.voice_state, "room": call.media_room,
            "joined_at": esc.voice_joined_at.isoformat() if esc.voice_joined_at else None, "specialist": esc.assignee}


async def participant_connected(call_id: str, identity: str) -> None:
    """Room event: someone connected. A specialist arriving starts the warm handover (LKH-08)."""
    state = ROOMS.get(call_id)
    if state is None or state.ended or not identity.startswith(PREFIX["specialist"]):
        return
    if state.voice_state not in ("waiting", "connected"):
        return
    async with state.lock:  # the AI's room connection and the scribe both report the same arrival
        await _specialist_arrived(state, identity)


async def _specialist_arrived(state: RoomState, identity: str) -> None:
    call_id = state.call_id
    if state.ended or (state.voice_state == "connected" and state.specialist_identity == identity):
        return
    state.specialist_identity = identity
    wait = state.tasks.pop("wait", None)
    if wait:
        wait.cancel()
    name = first_name(state.specialist or await _assignee(state))
    if state.ai_present:
        line = INTRO_LINE.format(name=name)
        await state.session.announce(line, {"handover_intro": True})
        try:
            await asyncio.wait_for(backend().say(call_id, line), AI_LEAVE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - the AI still leaves
            log.warning("introduction not spoken in %s: %s", state.room, type(exc).__name__)
        try:
            await asyncio.wait_for(backend().stop_ai(call_id), AI_LEAVE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("AI did not leave %s cleanly: %s", state.room, type(exc).__name__)
        state.ai_present = False
        await state.session.note("The AI left the call: handoff", {"segment_end": "handoff"})
    await _set_voice(state, "connected", joined=True)
    await _send(state, {"type": "handover", "state": "connected", "specialist": name})


async def _assignee(state: RoomState) -> str | None:
    async with sessionmaker()() as s:
        esc = await s.get(Escalation, state.session.state.escalation_id) if state.session.state.escalation_id else None
        return esc.assignee if esc else None


async def participant_disconnected(call_id: str, identity: str) -> None:
    """Room event: someone left. The customer ends the call (LKH-04); the specialist returns it to waiting (LKH-12)."""
    state = ROOMS.get(call_id)
    if state is None or state.ended:
        return
    if identity.startswith(PREFIX["customer"]):
        await end_call(state, "hangup")
    elif identity.startswith(PREFIX["specialist"]) and state.voice_state == "connected":
        await _set_voice(state, "waiting")
        await state.session.note("The specialist disconnected", {"specialist_dropped": True})
        await _send(state, {"type": "handover", "state": "waiting_again"})
        _restart_clock(state)  # no AI rejoins


async def transcript(call_id: str, identity: str, text: str, final: bool) -> None:
    """Room event from the scribe: one human track's speech (LKH-09). Customer finals are `user` events, the specialist's
    are `human` events with `source: voice`, in one `seq` order; partials are never stored."""
    state = ROOMS.get(call_id)
    text = (text or "").strip()
    if state is None or state.ended or not text or state.voice_state is None:
        return
    session = state.session
    if not final:
        if identity.startswith(PREFIX["customer"]):
            caller_partial(session, text)
        elif identity.startswith(PREFIX["specialist"]):
            bus.publish(state.tenant_id, f"call:{call_id}", "call.partial", {"call_id": call_id, "text": text, "speaker": "human"})
        return
    if identity.startswith(PREFIX["customer"]):
        seq = await session.record_room_line("user", text, {"to_human": True, "source": "voice"})
        speaker = "caller"
    elif identity.startswith(PREFIX["specialist"]):
        seq = await session.record_room_line("human", text, {"role": "specialist", "source": "voice", "participant": identity,
                                                              "author": state.specialist or "Specialist"})
        speaker = "human"
    else:
        return
    if session.state.escalation_id:
        bus.publish(state.tenant_id, "console", "escalation.message",
                    {"escalation_id": session.state.escalation_id, "seq": seq, "speaker": speaker})


async def end_call(state: RoomState, reason: str) -> None:
    """End a room call (idempotent): the session, the escalation's voice state, the browsers, then the room itself."""
    if state.ended:
        return
    state.ended = True
    me = asyncio.current_task()
    for key, task in list(state.tasks.items()):
        if task is not me:
            task.cancel()
    state.tasks.clear()
    await state.session.end(reason)
    esc_id = state.session.state.escalation_id
    if esc_id:
        from voiceai.runtime import escalation as esc_mod

        async with sessionmaker()() as s:
            esc = await s.get(Escalation, esc_id)
            if esc is not None:
                esc.voice_state = "ended"
                await s.commit()
                data = esc_mod.summary(esc)
                bus.publish(state.tenant_id, "console", "escalation.updated", {**data, "voice": "ended"})
    state.voice_state = "ended" if esc_id else state.voice_state
    await _send(state, {"type": "end", "reason": reason})
    for step in (backend().stop_ai(state.call_id) if state.ai_present else None, backend().close_room(state.room)):
        if step is None:
            continue
        try:
            await step
        except Exception as exc:  # noqa: BLE001
            log.warning("room cleanup in %s: %s", state.room, type(exc).__name__)
    ROOMS.pop(state.call_id, None)


async def resolved(tenant_id: str, call_id: str) -> None:
    """LKH-11: **Resolve** on a room call ends it `human_ended` and closes the room."""
    state = ROOMS.get(call_id)
    if state is not None:
        await end_call(state, "human_ended")
        return
    async with sessionmaker()() as s:  # the process restarted since: end the call row at least
        call = await s.get(Call, call_id)
        if call is None or not call.media_room or call.ended_at is not None:
            return
    from voiceai.runtime.session import AgentSession

    await (await AgentSession.open(call_id, tenant_id)).end("human_ended")
