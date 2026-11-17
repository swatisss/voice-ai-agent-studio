"""Warm handover of a phone call to a person: Twilio conference, brief, callbacks, recording rows, Agent Desk presence.

Spec: /architecture/phone-warm-handover.md, /architecture/telephony.md (Transfer to a person), /architecture/escalation.md,
/architecture/agent-desk.md, /data/data-model.md (call_recordings, desk_presence)

Every Twilio detail marked "spike" in the spec is unverified (no paid account): the primary path is implemented as documented.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs, mask, telephony
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.models import Call, CallEvent, CallRecording, DeskPresence, Escalation

log = logging.getLogger("voiceai.handover")

BRIEF_MAX = 300
GENERIC_BRIEF = "A caller needs a person. The details are on your Agent Desk."
APOLOGY = "I'm sorry, nobody is available right now. We have your request and a colleague will call you back."
PRESENCE_TTL_S = 90
TOKEN_TTL_S = 3600
XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>'
TERMINAL_LEG = {"no-answer", "busy", "failed", "canceled", "completed"}


@dataclass(frozen=True)
class Plan:
    mode: str = "dial"
    destination: str = ""
    record: bool = False
    ring_seconds: int = 30
    browser: bool = False
    brief: bool = True


def plan_of(telephony_cfg: dict[str, Any] | None) -> Plan:
    """The agent's `telephony` config as a plan; an agent without `handover` keeps today's cold `<Dial>` (TEL-07)."""
    cfg = telephony_cfg or {}
    h = cfg.get("handover") or {}
    dest = (cfg.get("transfer_to") or "").strip()
    return Plan(mode=h.get("mode", "dial"), destination=dest, record=bool(h.get("record", False)),
                ring_seconds=int(h.get("ring_seconds", 30)), browser=bool(h.get("browser", False)), brief=bool(h.get("brief", True)))


# ---------------------------------------------------------------- URLs and the Twilio REST client
def callback_url(kind: str, call_id: str) -> str:
    return telephony.public_url(f"/api/telephony/twilio/handover/{kind}/{call_id}")


def conference_name(call_id: str) -> str:
    return f"h-{call_id}"


_client_override: httpx.AsyncClient | None = None


def set_http_client(client: httpx.AsyncClient | None) -> None:
    """Tests install an httpx client on a MockTransport; nothing in the handover uses the network otherwise."""
    global _client_override
    _client_override = client


def http_client_override() -> httpx.AsyncClient | None:
    return _client_override


def _account_url(suffix: str) -> str:
    s = get_settings()
    return f"{s.twilio_api_base.rstrip('/')}/2010-04-01/Accounts/{s.twilio_account_sid}/{suffix}"


async def _rest(method: str, suffix: str, data: dict[str, Any] | None = None, auth: tuple[str, str] | None = None,
                params: dict[str, str] | None = None, client: httpx.AsyncClient | None = None) -> httpx.Response:
    s = get_settings()
    own = client is None and _client_override is None
    c = client or _client_override or httpx.AsyncClient(timeout=15)
    try:
        return await c.request(method, _account_url(suffix), data=data, params=params,
                               auth=auth or (s.twilio_account_sid or "", s.twilio_auth_token or ""))
    finally:
        if own:
            await c.aclose()


async def _update_call(call_sid: str, **fields: str) -> bool:
    try:
        resp = await _rest("POST", f"Calls/{call_sid}.json", data=fields)
    except Exception as exc:  # noqa: BLE001 - never raises: the call ends either way
        log.warning("Twilio call update failed for %s: %s", call_sid, type(exc).__name__)
        return False
    if resp.status_code >= 300:
        log.warning("Twilio call update failed for %s: HTTP %s", call_sid, resp.status_code)
        return False
    return True


# ---------------------------------------------------------------- the brief (TEL-19)
_XML_BREAKERS = str.maketrans({"<": " ", ">": " ", "&": " and ", '"': " ", "'": " "})


def build_brief(packet: dict[str, Any] | None, packet_status: str | None) -> str:
    """Spoken to the specialist: at most 300 characters, identifiers masked, nothing that breaks XML."""
    if packet_status not in ("ready", "fallback") or not packet:
        return GENERIC_BRIEF
    intent = str(packet.get("intent") or "unknown").replace("_", " ").strip()
    summary = str(packet.get("summary") or "").strip().rstrip(".!? ")
    action = str(packet.get("suggested_next_action") or "").strip().rstrip(".!? ")
    text = f"Caller for {intent}. {summary}." + (f" Suggested next step: {action}." if action else "")
    text = mask.text(text).translate(_XML_BREAKERS)
    return re.sub(r"\s+", " ", text).strip()[:BRIEF_MAX].rstrip()


# ---------------------------------------------------------------- TwiML (TEL-15, TEL-16, TEL-18, TEL-26)
def twiml_caller_conference(call_id: str, record: bool) -> str:
    s = get_settings()
    rec = ""
    if record:
        rec = (f' record="record-from-start" recordingStatusCallback={quoteattr(callback_url("recording", call_id))}'
               ' recordingStatusCallbackEvent="completed"')
    notice = f"<Say>{escape(s.twilio_recording_notice)}</Say>" if record else ""
    return (f'{XML_HEAD}<Response>{notice}<Dial><Conference startConferenceOnEnter="false" endConferenceOnExit="true" beep="false" '
            f'waitUrl={quoteattr(s.twilio_hold_url or "")} participantLabel="caller"{rec} '
            f'statusCallback={quoteattr(callback_url("conference", call_id))} statusCallbackEvent="start end join leave">'
            f'{escape(conference_name(call_id))}</Conference></Dial></Response>')


def twiml_specialist(call_id: str, brief: str | None) -> str:
    say = f"<Say>{escape(brief)}</Say>" if brief else ""
    return (f'{XML_HEAD}<Response>{say}<Dial><Conference startConferenceOnEnter="true" endConferenceOnExit="false" beep="false" '
            f'participantLabel="specialist" statusCallback={quoteattr(callback_url("conference", call_id))} '
            f'statusCallbackEvent="start end join leave">{escape(conference_name(call_id))}</Conference></Dial></Response>')


def twiml_apology() -> str:
    return f"{XML_HEAD}<Response><Say>{escape(APOLOGY)}</Say><Hangup/></Response>"


# ---------------------------------------------------------------- call meta and events
_locks: dict[str, asyncio.Lock] = {}


def _lock(call_id: str) -> asyncio.Lock:
    return _locks.setdefault(call_id, asyncio.Lock())


async def add_event(s: AsyncSession, call: Call, kind: str, text: str, data: dict[str, Any] | None = None, at: datetime | None = None) -> CallEvent:
    seq = (await s.scalar(select(func.max(CallEvent.seq)).where(CallEvent.call_id == call.id))) or 0
    ev = CallEvent(tenant_id=call.tenant_id, call_id=call.id, seq=seq + 1, kind=kind, text=text, data=data or {})
    if at is not None:
        ev.at = at
    s.add(ev)
    await s.flush()
    return ev


def _now() -> str:
    return utcnow().isoformat()


async def _write(call_id: str, apply: Any) -> bool:  # noqa: ANN401
    """Read-modify-write of `calls.meta.handover` under a per-call lock; `apply(s, call, h)` may add events.
    True when the call has a handover, else False (the callback answers 404)."""
    async with _lock(call_id):
        async with sessionmaker()() as s:
            call = await s.get(Call, call_id)
            if call is None or "handover" not in (call.meta or {}):
                return False
            h = json.loads(json.dumps(call.meta["handover"]))
            await apply(s, call, h)
            call.meta = {**(call.meta or {}), "handover": h}
            await s.commit()
            return True


# ---------------------------------------------------------------- Ready specialists
def identity_of(email: str) -> str:
    return "desk-" + (re.sub(r"[^A-Za-z0-9_]", "_", email or "") or "studio")


async def ready_specialists(s: AsyncSession, tenant_id: str) -> list[DeskPresence]:
    cutoff = utcnow() - timedelta(seconds=PRESENCE_TTL_S)
    return list((await s.scalars(select(DeskPresence).where(
        DeskPresence.tenant_id == tenant_id, DeskPresence.ready.is_(True), DeskPresence.updated_at >= cutoff))).all())


async def set_presence(s: AsyncSession, tenant_id: str, email: str, ready: bool) -> None:
    row = await s.scalar(select(DeskPresence).where(DeskPresence.tenant_id == tenant_id, DeskPresence.user_email == email))
    if row is None:
        row = DeskPresence(tenant_id=tenant_id, user_email=email)
        s.add(row)
    row.ready, row.updated_at = ready, utcnow()
    await s.commit()


def voice_sdk_configured() -> bool:
    s = get_settings()
    return bool(s.twilio_api_key_sid and s.twilio_api_key_secret and s.twilio_account_sid)


def access_token(identity: str, now: float | None = None) -> str:
    """A Twilio Access Token (JWT, HS256) with the Voice grant: incoming calls allowed, no outgoing application."""
    s = get_settings()
    iat = int(time.time() if now is None else now)

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = {"typ": "JWT", "alg": "HS256", "cty": "twilio-fpa;v=1"}
    payload = {"jti": f"{s.twilio_api_key_sid}-{iat}", "iss": s.twilio_api_key_sid, "sub": s.twilio_account_sid, "iat": iat,
               "exp": iat + TOKEN_TTL_S, "grants": {"identity": identity, "voice": {"incoming": {"allow": True}}}}
    signing = f"{b64(json.dumps(header, separators=(',', ':')).encode())}.{b64(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = hmac.new((s.twilio_api_key_secret or "").encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{b64(sig)}"


# ---------------------------------------------------------------- starting a handover (TEL-15, TEL-16)
async def _targets(s: AsyncSession, tenant_id: str, plan: Plan) -> list[dict[str, str]]:
    legs: list[dict[str, str]] = []
    if plan.destination and re.fullmatch(r"\+[1-9][0-9]{6,14}", plan.destination):
        legs.append({"kind": "phone", "to": plan.destination})
    if plan.browser and voice_sdk_configured():  # without an API key the browser leg is off
        from voiceai import auth

        for row in await ready_specialists(s, tenant_id):
            user = auth.account(row.user_email)
            legs.append({"kind": "browser", "to": f"client:{identity_of(row.user_email)}", "email": row.user_email,
                         "name": user.name if user else "Specialist"})
    return legs


async def on_escalated_call_end(session: Any, call_sid: str, plan: Plan) -> None:  # noqa: ANN401
    """Mode `conference`: put the caller in a conference and ring the specialist. Never raises; failures leave a `system` event."""
    s_ = get_settings()
    tenant_id, call_id = getattr(session, "tenant_id", None), getattr(session, "call_id", None)
    if not (tenant_id and call_id and s_.twilio_account_sid and s_.twilio_auth_token):
        return
    async with sessionmaker()() as s:
        legs = await _targets(s, tenant_id, plan)
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        brief = build_brief(esc.packet if esc else None, esc.packet_status if esc else None) if plan.brief else None
        call = await s.get(Call, call_id)
        meta = dict(call.meta or {}) if call else {}
    from_number = s_.twilio_from_number or (meta.get("telephony") or {}).get("to")
    if not legs or not from_number:
        await session.note("handover_failed", {"event": "handover_failed", "reason": "no destination to ring" if not legs else "no caller ID"})
        return
    h = {"mode": "conference", "state": "pending", "conference": conference_name(call_id), "caller_sid": call_sid, "started_at": _now(),
         "record": plan.record, "legs": {}, "join_order": []}
    async with sessionmaker()() as s:
        call = await s.get(Call, call_id)
        if call is None:
            return
        call.meta = {**(call.meta or {}), "handover": h}
        await s.commit()
    await session.note("handover_started", {"event": "handover_started", "mode": "conference", "record": plan.record})
    if not await _update_call(call_sid, Twiml=twiml_caller_conference(call_id, plan.record)):  # TEL-15: the update failed: no specialist call
        await _set_state(call_id, "failed", "handover_failed", {"status": "caller_update_failed"}, session=session)
        return
    created = 0
    for leg in legs:
        data = {"To": leg["to"], "From": from_number, "Timeout": str(plan.ring_seconds),
                "StatusCallback": callback_url("specialist", call_id),
                "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
                "Twiml": twiml_specialist(call_id, brief)}
        try:
            resp = await _rest("POST", "Calls.json", data=data)
            sid = resp.json().get("sid") if resp.status_code < 300 else None
        except Exception as exc:  # noqa: BLE001
            log.warning("Twilio specialist leg failed: %s", type(exc).__name__)
            sid = None
        if sid:
            created += 1
            await _write(call_id, lambda s, c, h, sid=sid, leg=leg: _add_leg(h, sid, leg))
    if not created:
        await _set_state(call_id, "failed", "handover_failed", {"status": "no_leg_created"}, session=session, apologise=True)
        return
    await _write(call_id, _ringing)


async def _add_leg(h: dict[str, Any], sid: str, leg: dict[str, str]) -> None:
    h["legs"][sid] = {"kind": leg["kind"], "status": "initiated", **({k: leg[k] for k in ("email", "name") if k in leg})}


async def _ringing(s: AsyncSession, call: Call, h: dict[str, Any]) -> None:  # noqa: ARG001
    if h["state"] == "pending":  # a join callback may already have connected the call
        h["state"] = "ringing"


async def _set_state(call_id: str, state: str, event: str, data: dict[str, Any], session: Any = None, apologise: bool = False) -> None:  # noqa: ANN401
    caller_sid: list[str] = []

    async def apply(s: AsyncSession, call: Call, h: dict[str, Any]) -> None:
        h["state"] = state
        caller_sid.append(h.get("caller_sid", ""))
        if session is not None:
            return
        await add_event(s, call, "system", event, {"event": event, **data})

    await _write(call_id, apply)
    if session is not None:
        await session.note(event, {"event": event, **data})
    if apologise and caller_sid and caller_sid[0]:
        await _update_call(caller_sid[0], Twiml=twiml_apology())


def dial_record_attributes(call_id: str | None) -> str:
    """TEL-16: `record="record-from-answer-dual"` and the recording callback, only with record true."""
    if not call_id:
        return ""
    return (' record="record-from-answer-dual" recordingStatusCallback='
            f'{quoteattr(callback_url("recording", call_id))} recordingStatusCallbackEvent="completed"')


async def mark_dial(call_id: str, call_sid: str) -> None:
    """A recorded cold transfer (mode `dial`, record true): the recording callback needs a handover record on the call."""
    async with sessionmaker()() as s:
        call = await s.get(Call, call_id)
        if call is None:
            return
        call.meta = {**(call.meta or {}), "handover": {"mode": "dial", "state": "connected", "caller_sid": call_sid, "started_at": _now(),
                                                        "record": True, "legs": {}, "join_order": []}}
        await s.commit()


# ---------------------------------------------------------------- callbacks (TEL-17, TEL-18, TEL-20)
def _event_name(raw: str) -> str:
    return (raw or "").strip().lower().removeprefix("participant-").removeprefix("conference-")


async def on_conference_event(call_id: str, form: dict[str, str]) -> bool:
    """`join`, `leave`, `start`, `end` of the conference. Returns False when the call has no handover (404)."""
    ev, label, sid = _event_name(form.get("StatusCallbackEvent", "")), form.get("ParticipantLabel", ""), form.get("CallSid", "")
    cancel: list[str] = []
    accept: list[dict[str, str]] = []

    async def apply(s: AsyncSession, call: Call, h: dict[str, Any]) -> None:
        if ev == "join":
            if label and label not in h["join_order"]:
                h["join_order"].append(label)
            if label == "specialist" and h["state"] in ("pending", "ringing"):
                leg = h["legs"].get(sid) or {}
                kind = leg.get("kind", "phone")
                h.update(state="connected", answered_by=kind, connected_at=_now(), answered_leg=sid)
                if sid in h["legs"]:
                    h["legs"][sid]["status"] = "in-progress"
                cancel.extend(k for k, v in h["legs"].items() if k != sid and v.get("status") not in TERMINAL_LEG)
                for k in cancel:
                    h["legs"][k]["status"] = "canceled"
                await add_event(s, call, "system", "handover_connected", {"event": "handover_connected", "answered_by": kind})
                if kind == "browser":
                    accept.append({"name": leg.get("name") or "Specialist"})
        elif ev == "end" and h["state"] in ("pending", "ringing", "connected"):
            was = h["state"]
            if was != "connected":
                cancel.extend(k for k, v in h["legs"].items() if v.get("status") not in TERMINAL_LEG)
            h.update(state="ended", ended_at=_now())
            length = 0
            if h.get("connected_at"):
                length = int((datetime.fromisoformat(h["ended_at"]) - datetime.fromisoformat(h["connected_at"])).total_seconds())
            await add_event(s, call, "system", "handover_ended", {"event": "handover_ended", "seconds": length, "connected": was == "connected"})

    if not await _write(call_id, apply):
        return False
    for leg_sid in cancel:
        await _update_call(leg_sid, Status="canceled")
    if accept:
        await _accept_escalation(call_id, accept[0]["name"])
    return True


async def _accept_escalation(call_id: str, name: str) -> None:
    """A browser answer accepts the escalation for that specialist: a no-op unless it is waiting."""
    from voiceai.runtime import escalation as esc_mod

    async with sessionmaker()() as s:
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        if esc is None:
            return
        try:
            await esc_mod.accept(s, esc.tenant_id, esc.id, name)
        except ApiError:
            return


async def on_specialist_status(call_id: str, form: dict[str, str]) -> bool:
    """A specialist leg's own status: when every leg ended without a join, the caller hears the apology (TEL-18)."""
    sid, status = form.get("CallSid", ""), (form.get("CallStatus") or "").lower()
    outcome: dict[str, Any] = {}

    async def apply(s: AsyncSession, call: Call, h: dict[str, Any]) -> None:
        leg = h["legs"].get(sid)
        if leg is None or leg.get("status") == status:
            return
        if leg.get("status") in TERMINAL_LEG:
            return  # a terminal status is final
        leg["status"] = status
        if h["state"] not in ("pending", "ringing") or not h["legs"]:
            return
        legs = h["legs"].values()
        if all(v.get("status") in TERMINAL_LEG for v in legs):
            state = "failed" if all(v.get("status") == "failed" for v in legs) else "no_answer"
            h["state"] = state
            await add_event(s, call, "system", "handover_failed", {"event": "handover_failed", "status": status})
            outcome["caller_sid"] = h.get("caller_sid")

    if not await _write(call_id, apply):
        return False
    if outcome.get("caller_sid"):
        await _update_call(outcome["caller_sid"], Twiml=twiml_apology())
    return True


async def on_recording(call_id: str, form: dict[str, str]) -> bool:
    """A recording status callback: one row per RecordingSid, one `transcribe_handover` job when it is completed (TEL-21, TEL-23)."""
    sid, status = form.get("RecordingSid", ""), (form.get("RecordingStatus") or "").lower()
    if not sid:
        async with sessionmaker()() as s:
            call = await s.get(Call, call_id)
            return bool(call and "handover" in (call.meta or {}))
    s_ = get_settings()
    async def apply(s: AsyncSession, call: Call, h: dict[str, Any]) -> None:
        channels = int(form.get("RecordingChannels") or 1)
        duration = int(float(form.get("RecordingDuration") or 0))
        row = await s.scalar(select(CallRecording).where(CallRecording.recording_sid == sid))
        if row is None:
            order = h.get("join_order") or []
            if channels < 2:
                cmap = None
            elif h.get("mode") == "dial" or not order or order[0] != "specialist":
                cmap = {"1": "caller", "2": "specialist"}
            else:
                cmap = {"1": "specialist", "2": "caller"}
            row = CallRecording(tenant_id=call.tenant_id, call_id=call.id, recording_sid=sid, source=h.get("mode", "conference"),
                                channels=channels, duration_s=duration, channel_map=cmap)
            s.add(row)
            await s.flush()
        elif status == "completed":
            row.channels, row.duration_s = channels, duration or row.duration_s
        if status == "absent":
            row.status, row.error = "failed", "recording absent"
        if status == "completed" and row.status == "received":
            if not (s_.twilio_api_key_sid and s_.twilio_api_key_secret):
                row.status, row.error = "failed", "no_api_key"
                await add_event(s, call, "system", "Recording not transcribed: TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET are not set",
                                {"event": "recording_not_transcribed", "recording_id": row.id})
            else:
                await jobs.enqueue(s, call.tenant_id, "transcribe_handover", {"recording_id": row.id}, dedupe_key=f"transcribe_handover:{row.id}")

    return await _write(call_id, apply)
