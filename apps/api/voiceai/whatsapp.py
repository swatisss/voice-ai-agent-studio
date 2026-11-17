"""WhatsApp through Twilio as a text channel: threads and the 24-hour window, the inbound turn, delivery of specialist replies,
opt-out, voice notes, privacy and retention.

Spec: /architecture/whatsapp-channel.md, /architecture/human-message-channel.md, /architecture/escalation.md (ES-14),
/architecture/agent-desk.md (DESK-12), /data/data-model.md (whatsapp_senders, whatsapp_threads, DM-20)

Twilio details marked "spike" in the spec (S6 receipt field names and the out-of-window error code, S7 voice note type and download,
S8 payloads without a phone number) are unverified because no Twilio account exists: the documented primary path is implemented
and each fallback is defensive. The user's full address lives only in `whatsapp_threads.address`; everywhere else it is `wa-…{last4}`.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import struct
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import conversations, handover, mask, telephony
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.models import (Agent, AgentVersion, Call, CallEvent, Conversation, Escalation, Tenant, WhatsappSender, WhatsappThread)

log = logging.getLogger("voiceai.whatsapp")

ADDRESS_RE = re.compile(r"^whatsapp:\+[1-9][0-9]{6,14}$")
STOP_WORDS = {"stop", "unsubscribe", "cancel"}
MAX_PART = 1500
WINDOW = timedelta(hours=24)
IDLE_AFTER = timedelta(hours=72)
MAX_MEDIA_BYTES = 10 * 1024 * 1024
MAX_MEDIA_SECONDS = 120
OUT_OF_WINDOW_CODE = 63016  # Twilio: "freeform message outside the allowed window" (spike S6: unverified)
OPT_OUT_CONFIRMATION = "You will not get more messages from us. Message us again any time to start over."
VOICE_NOTE_FAILED = "I couldn't process that voice note. Could you type your message?"
ATTACHMENT_NOTICE = "I can't read pictures or documents yet. Please type what you need."
RANK = {"queued_template": 0, "sending": 0, "sent": 1, "delivered": 2, "read": 3}
RECEIPT_STATES = {"sent", "delivered", "read", "failed", "undelivered"}


# ---------------------------------------------------------------- clock (tests replace both)
_now = time.monotonic
_sleep = asyncio.sleep
_last_send: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def reset_state() -> None:
    _last_send.clear()
    _locks.clear()


def window_open(thread: WhatsappThread, now: datetime | None = None) -> bool:
    return bool(thread.window_expires_at and (now or utcnow()) < thread.window_expires_at)


def last4(address: str) -> str:
    return re.sub(r"\D", "", address)[-4:]


# ---------------------------------------------------------------- text helpers
def plain(text: str) -> str:
    """WhatsApp replies are plain text: no markdown markers."""
    text = re.sub(r"```+", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "- ", text)
    return text.replace("`", "").strip()


def split_text(text: str, limit: int = MAX_PART) -> list[str]:
    """Parts of at most `limit` characters, split on sentence boundaries (a long word is cut as a last resort)."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    parts: list[str] = []
    cur = ""
    for sentence in sentences:
        while len(sentence) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if cur and len(cur) + 1 + len(sentence) > limit:
            parts.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        parts.append(cur)
    return parts


# ---------------------------------------------------------------- Twilio REST
@dataclass
class Sent:
    ok: bool
    sid: str | None = None
    code: int | None = None  # Twilio error code, e.g. 63016
    error: str | None = None


def status_url() -> str | None:
    return telephony.public_url("/api/channels/twilio/whatsapp/status") if get_settings().public_base_url else None


async def _post_message(sender: WhatsappSender, to: str, fields: dict[str, str]) -> Sent:
    s = get_settings()
    if not (s.twilio_account_sid and s.twilio_auth_token):
        return Sent(False, error="not_configured")
    data = {"To": to, **fields}
    if s.twilio_messaging_service_sid:
        data["MessagingServiceSid"] = s.twilio_messaging_service_sid
    else:
        data["From"] = sender.address or s.twilio_whatsapp_from or ""
    if cb := status_url():
        data["StatusCallback"] = cb
    try:
        resp = await handover._rest("POST", "Messages.json", data=data)
    except Exception as exc:  # noqa: BLE001 - a send never raises into a request or a turn
        log.warning("WhatsApp send failed to wa-…%s: %s", last4(to), type(exc).__name__)
        return Sent(False, error=type(exc).__name__)
    body: dict[str, Any] = {}
    try:
        body = resp.json()
    except ValueError:
        pass
    if resp.status_code >= 300:
        code = body.get("code") if isinstance(body.get("code"), int) else None
        log.warning("WhatsApp send to wa-…%s refused: HTTP %s code %s", last4(to), resp.status_code, code)
        return Sent(False, code=code, error=f"HTTP {resp.status_code}")
    return Sent(True, sid=str(body.get("sid") or ""))


def interval_for(sender: WhatsappSender) -> float:
    configured = get_settings().whatsapp_min_send_interval_s
    return configured if configured is not None else (3.0 if sender.mode == "sandbox" else 0.0)


async def _pace(sender: WhatsappSender) -> None:
    """WA-04: a sandbox sender sends at most one message per 3 seconds."""
    interval = interval_for(sender)
    last = _last_send.get(sender.id)
    if interval and last is not None:
        wait = last + interval - _now()
        if wait > 0:
            await _sleep(wait)
    _last_send[sender.id] = _now()


async def send_free_text(sender: WhatsappSender, address: str, text: str) -> list[Sent]:
    """Plain text in parts of at most 1,500 characters, in order, paced; stops at the first failure."""
    out: list[Sent] = []
    for part in split_text(plain(text)):
        await _pace(sender)
        result = await _post_message(sender, address, {"Body": part})
        out.append(result)
        if not result.ok:
            break
    return out


async def send_template(sender: WhatsappSender, address: str, variable: str) -> Sent:
    """The approved follow-up template through the Messages API with `ContentSid` (production only)."""
    await _pace(sender)
    return await _post_message(sender, address, {"ContentSid": get_settings().twilio_whatsapp_followup_content_sid or "",
                                                 "ContentVariables": json.dumps({"1": variable})})


# ---------------------------------------------------------------- senders and threads
async def sender_by_address(s: AsyncSession, address: str) -> WhatsappSender | None:
    return await s.scalar(select(WhatsappSender).where(WhatsappSender.address == address))


async def thread_of(s: AsyncSession, conv: Conversation) -> WhatsappThread | None:
    return await s.scalar(select(WhatsappThread).where(WhatsappThread.conversation_id == conv.id, WhatsappThread.tenant_id == conv.tenant_id)
                          .order_by(WhatsappThread.created_at.desc()))


async def channel_state(s: AsyncSession, conv: Conversation | None) -> dict[str, Any] | None:
    """API-23, WA-09: the window and delivery state a specialist sees; the user's address only as `address_last4`."""
    if conv is None or conv.source != "whatsapp":
        return None
    thread = await thread_of(s, conv)
    if thread is None:
        return None
    sender = await s.get(WhatsappSender, thread.sender_id)
    return {"channel": "whatsapp", "window_open": window_open(thread),
            "window_expires_at": thread.window_expires_at.isoformat() if thread.window_expires_at else None,
            "opted_out": thread.status == "opted_out", "mode": sender.mode if sender else "sandbox", "address_last4": thread.address_last4}


async def health(s: AsyncSession) -> bool:
    """WA-15: account credentials and at least one sender row; no network call."""
    st = get_settings()
    if not (st.twilio_account_sid and st.twilio_auth_token):
        return False
    return (await s.scalar(select(func.count()).select_from(WhatsappSender)) or 0) > 0


def _lock(thread_id: str) -> asyncio.Lock:
    return _locks.setdefault(thread_id, asyncio.Lock())


# ---------------------------------------------------------------- inbound
@dataclass
class Inbound:
    sid: str
    sender_address: str
    address: str
    body: str
    num_media: int
    media_url: str | None
    media_type: str | None


def parse_inbound(params: dict[str, str]) -> Inbound | None:
    """None when the payload has no usable `From` (spike S8: a user with a username has no phone number) or `To`."""
    frm, to = (params.get("From") or "").strip(), (params.get("To") or "").strip()
    if not ADDRESS_RE.fullmatch(frm) or not ADDRESS_RE.fullmatch(to):
        return None
    try:
        n = int(params.get("NumMedia") or 0)
    except ValueError:
        n = 0
    return Inbound(sid=(params.get("MessageSid") or params.get("SmsMessageSid") or "").strip(), sender_address=to, address=frm,
                   body=(params.get("Body") or "").strip(), num_media=n, media_url=params.get("MediaUrl0") or None,
                   media_type=(params.get("MediaContentType0") or "").lower() or None)


async def accept_inbound(inbound: Inbound) -> str | None:
    """Synchronous part of the webhook: find or open the thread, move the window, drop a repeated `MessageSid`.

    Returns the thread id to process in the background, or None when there is nothing to do (WA-02, WA-03, WA-04).
    """
    async with sessionmaker()() as s:
        sender = await sender_by_address(s, inbound.sender_address)
        if sender is None:
            return None
        threads = (await s.scalars(select(WhatsappThread).where(
            WhatsappThread.sender_id == sender.id, WhatsappThread.address == inbound.address, WhatsappThread.status != "ended")
            .order_by(WhatsappThread.created_at.desc()))).all()
        thread = threads[0] if threads else None
        if thread is not None and inbound.sid and thread.last_message_sid == inbound.sid:
            return None  # a retry of the same message
        if thread is not None and thread.conversation_id:
            conv = await s.get(Conversation, thread.conversation_id)
            if conv is None or conv.status == "ended":  # WA-13: the next message opens a new conversation
                thread.status = "ended"
                thread = None
        now = utcnow()
        if thread is None:
            thread = WhatsappThread(tenant_id=sender.tenant_id, sender_id=sender.id, address=inbound.address, address_last4=last4(inbound.address),
                                    queued=[])
            s.add(thread)
        thread.last_inbound_at, thread.window_expires_at, thread.last_message_sid = now, now + WINDOW, inbound.sid or None
        await s.commit()
        return thread.id


async def process_inbound(app: Any, thread_id: str, inbound: Inbound) -> None:  # noqa: ANN401
    """Background part of the webhook: everything that may be slow. Messages of one thread run one at a time, in order."""
    async with _lock(thread_id):
        try:
            await _process(app, thread_id, inbound)
        except Exception:  # noqa: BLE001 - never lets a failed turn break the webhook worker
            log.exception("WhatsApp inbound processing failed for wa-…%s", last4(inbound.address))


async def _process(app: Any, thread_id: str, inbound: Inbound) -> None:  # noqa: ANN401
    async with sessionmaker()() as s:
        thread = await s.get(WhatsappThread, thread_id)
        sender = await s.get(WhatsappSender, thread.sender_id) if thread else None
        if thread is None or sender is None or not thread.address:
            return
        address = thread.address
        if inbound.body.lower() in STOP_WORDS:  # WA-10
            thread.status = "opted_out"
            await s.commit()
            await _send_plain(sender, address, OPT_OUT_CONFIRMATION)
            return
        if thread.status == "opted_out":
            thread.status = "active"
            await s.commit()
        queued = list(thread.queued or [])
    if queued:
        await flush_queue(thread_id)

    text, voice = inbound.body, False
    if inbound.num_media >= 1 and not inbound.body:
        if (inbound.media_type or "").startswith("audio/"):
            transcript = await _voice_note(sender, thread_id, inbound)
            if transcript is None:
                await _send_plain(sender, address, VOICE_NOTE_FAILED)
                return
            text, voice = transcript, True
        else:
            await _attachment(sender, thread_id, address, inbound)
            return
    if not text:
        return
    text = text[:2000]

    async with sessionmaker()() as s:
        thread = await s.get(WhatsappThread, thread_id)
        conv = await s.get(Conversation, thread.conversation_id) if thread and thread.conversation_id else None
    if conv is not None and conv.status == "escalated":  # WA-06, HMC-01: stored for the specialist, nothing is replied
        await conversations.human_line(conv, text, {"voice_note": True} if voice else None)
        return
    messages, new = await _turn(app, sender, thread_id, conv, text)
    if voice and messages is not None:
        await _mark_voice_note(thread_id, text)
    if not messages:
        return
    texts = [m["text"] for m in messages if m.get("text")]
    if new and texts and not texts[0].lower().startswith("i'm a virtual assistant"):  # the persona's own welcome usually says it
        texts[0] = f"{await _disclosure(sender.tenant_id)} {texts[0]}"
    for t in texts:
        await _send_plain(sender, address, t)


async def _disclosure(tenant_id: str) -> str:
    async with sessionmaker()() as s:
        tenant = await s.get(Tenant, tenant_id)
    return f"I'm a virtual assistant for {tenant.name if tenant else 'this business'}."


async def _turn(app: Any, sender: WhatsappSender, thread_id: str, conv: Conversation | None, text: str  # noqa: ANN401
                ) -> tuple[list[dict[str, Any]] | None, bool]:
    """The text turn of the public API (the same code): returns the messages to send and whether the conversation is new."""
    if conv is None:
        body = conversations.CreateBody(channel="text", agent_id=sender.agent_id if sender.target == "agent" else None, message=text)
        try:
            async with sessionmaker()() as s:
                result = await conversations.create(s, sender.tenant_id, body, source="whatsapp", scope="member", app=app)
        except ApiError as exc:  # e.g. a front desk with no routable agent: nothing to say on WhatsApp
            log.warning("WhatsApp conversation not opened: %s", exc.error)
            return None, True
        async with sessionmaker()() as s:
            row = await s.get(Conversation, result["conversation_id"])
            thread = await s.get(WhatsappThread, thread_id)
            row.transport = "twilio"
            row.metadata_ = {"user": mask.wa_ref(f"whatsapp:+{thread.address_last4}")}
            thread.conversation_id = row.id
            await s.commit()
        return list(result.get("messages") or []), True
    try:
        turn = await conversations.message(conv, text, app)
    except ApiError as exc:
        log.warning("WhatsApp turn refused: %s", exc.error)
        return None, False
    return list(turn.get("messages") or []), False


async def _send_plain(sender: WhatsappSender, address: str, text: str) -> None:
    await send_free_text(sender, address, text)


async def _mark_voice_note(thread_id: str, text: str) -> None:
    """WA-11: the customer's event carries `data.voice_note`."""
    async with sessionmaker()() as s:
        thread = await s.get(WhatsappThread, thread_id)
        if thread is None or not thread.conversation_id:
            return
        ev = await s.scalar(select(CallEvent).join(Call, Call.id == CallEvent.call_id)
                            .where(Call.conversation_id == thread.conversation_id, CallEvent.kind == "user", CallEvent.text == text)
                            .order_by(CallEvent.at.desc()))
        if ev is not None:
            ev.data = {**(ev.data or {}), "voice_note": True}
            await s.commit()


# ---------------------------------------------------------------- voice notes and attachments
def audio_seconds(data: bytes, content_type: str) -> float | None:
    """Duration of a WAV or Ogg Opus file; None when it cannot be told (only the size cap applies then)."""
    try:
        if data[:4] == b"RIFF":
            with wave.open(io.BytesIO(data), "rb") as w:
                return w.getnframes() / float(w.getframerate())
        if data[:4] == b"OggS":
            at = data.rfind(b"OggS")
            granule = struct.unpack_from("<q", data, at + 6)[0]
            return granule / 48000.0 if granule > 0 else None
    except Exception:  # noqa: BLE001
        return None
    return None


async def _download_media(url: str) -> bytes | None:
    """The media file in memory (HTTP Basic with the account credentials, spike S7); None when it is too big or cannot be fetched."""
    s = get_settings()
    override = handover.http_client_override()
    client = override or httpx.AsyncClient(timeout=30, follow_redirects=True)
    try:
        resp = await client.get(url, auth=(s.twilio_account_sid or "", s.twilio_auth_token or ""), follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("WhatsApp media download failed: %s", type(exc).__name__)
        return None
    finally:
        if override is None:
            await client.aclose()
    if resp.status_code >= 300:
        log.warning("WhatsApp media download failed: HTTP %s", resp.status_code)
        return None
    declared = int(resp.headers.get("content-length") or 0)
    if declared > MAX_MEDIA_BYTES or len(resp.content) > MAX_MEDIA_BYTES:
        return None
    return resp.content


async def _voice_note(sender: WhatsappSender, thread_id: str, inbound: Inbound) -> str | None:
    """WA-11: download, check the caps, transcribe with CP-0051's `Transcriber`; the audio is never stored."""
    from voiceai.voice import transcribe

    transcriber = transcribe.get_transcriber()
    if transcriber is None or not inbound.media_url:
        return None
    data = await _download_media(inbound.media_url)
    if data is None:
        return None
    seconds = audio_seconds(data, inbound.media_type or "")
    if seconds is not None and seconds > MAX_MEDIA_SECONDS:
        return None
    async with sessionmaker()() as s:
        languages: list[str] = []
        if sender.target == "agent" and sender.agent_id:
            agent = await s.get(Agent, sender.agent_id)
            version = await s.get(AgentVersion, agent.published_version_id) if agent and agent.published_version_id else None
            languages = list(((version.config if version else None) or {}).get("languages") or [])
    try:
        segments = await transcriber.transcribe(data, languages)
    except Exception as exc:  # noqa: BLE001
        log.warning("WhatsApp voice note transcription failed: %s", type(exc).__name__)
        return None
    text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
    return text or None


async def _attachment(sender: WhatsappSender, thread_id: str, address: str, inbound: Inbound) -> None:
    """WA-11: pictures and documents are not read; the customer is told once, an escalated specialist sees a marker."""
    async with sessionmaker()() as s:
        thread = await s.get(WhatsappThread, thread_id)
        conv = await s.get(Conversation, thread.conversation_id) if thread.conversation_id else None
        notice = not thread.attachment_notice_sent
        if notice:
            thread.attachment_notice_sent = True
            await s.commit()
    if conv is not None and conv.status == "escalated":
        await conversations.human_line(conv, f"[attachment: {inbound.media_type or 'file'}]", {"attachment": inbound.media_type})
    if notice:
        await _send_plain(sender, address, ATTACHMENT_NOTICE)


# ---------------------------------------------------------------- specialist replies (WA-07, WA-08)
async def plan_reply(s: AsyncSession, conv: Conversation) -> str:
    """`free` or `template`; 409 `opted_out`, `window_closed` (sandbox) or `template_not_configured`, before anything is stored."""
    thread = await thread_of(s, conv)
    if thread is None or not thread.address:
        raise ApiError(409, "address_unavailable", "The customer's WhatsApp address is no longer held")
    if thread.status == "opted_out":
        raise ApiError(409, "opted_out", "The customer has opted out of messages")
    if window_open(thread):
        return "free"
    sender = await s.get(WhatsappSender, thread.sender_id)
    if sender is None or sender.mode == "sandbox":
        raise ApiError(409, "window_closed", "Sandbox: replies only inside the 24-hour window")
    if not get_settings().twilio_whatsapp_followup_content_sid:
        raise ApiError(409, "template_not_configured", "The 24-hour window is closed and no follow-up template is configured")
    return "template"


async def _set_event(call_id: str, seq: int, **fields: Any) -> None:  # noqa: ANN401
    async with sessionmaker()() as s:
        ev = await s.scalar(select(CallEvent).where(CallEvent.call_id == call_id, CallEvent.seq == seq))
        if ev is not None:
            ev.data = {**(ev.data or {}), **fields}
            await s.commit()


async def _publish_updated(tenant_id: str, call_id: str) -> None:
    from voiceai.runtime import escalation as esc_mod

    async with sessionmaker()() as s:
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        if esc is not None:
            bus.publish(tenant_id, "console", "escalation.updated", esc_mod.summary(esc))


async def deliver_reply(tenant_id: str, conv_id: str, call_id: str, seq: int, text: str, plan: str, author: str = "") -> str:
    """Hand a stored `human` event to Twilio; returns its `delivery` (`sent`, `queued_template`, `failed`)."""
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, conv_id)
        thread = await thread_of(s, conv) if conv else None
        sender = await s.get(WhatsappSender, thread.sender_id) if thread else None
        tenant = await s.get(Tenant, tenant_id)
    if thread is None or sender is None or not thread.address:
        await _set_event(call_id, seq, delivery="failed")
        return "failed"
    address = thread.address
    if plan == "free":
        results = await send_free_text(sender, address, text)
        if results and all(r.ok for r in results):
            await _set_event(call_id, seq, delivery="sent", message_sids=[r.sid for r in results if r.sid])
            await _publish_updated(tenant_id, call_id)
            return "sent"
        failed = results[-1] if results else Sent(False)
        if failed.code == OUT_OF_WINDOW_CODE and sender.mode == "production" and get_settings().twilio_whatsapp_followup_content_sid:
            plan = "template"  # the clock and WhatsApp differ by a moment: the template path, once
        else:
            await _set_event(call_id, seq, delivery="failed", delivery_error=failed.code or failed.error)
            await _publish_updated(tenant_id, call_id)
            return "failed"
    sent = await send_template(sender, address, (author or "").split(" ")[0] or (tenant.name if tenant else "us"))
    if not sent.ok:
        await _set_event(call_id, seq, delivery="failed", delivery_error=sent.code or sent.error)
        await _publish_updated(tenant_id, call_id)
        return "failed"
    async with sessionmaker()() as s:
        row = await s.get(WhatsappThread, thread.id)
        row.queued = [*(row.queued or []), {"call_id": call_id, "seq": seq, "text": text}]
        await s.commit()
    await _set_event(call_id, seq, delivery="queued_template")
    await _publish_updated(tenant_id, call_id)
    return "queued_template"


async def flush_queue(thread_id: str) -> None:
    """The customer replied: queued specialist texts go out as free-form, in order."""
    async with sessionmaker()() as s:
        thread = await s.get(WhatsappThread, thread_id)
        sender = await s.get(WhatsappSender, thread.sender_id) if thread else None
        items = list(thread.queued or []) if thread else []
        address = thread.address if thread else None
        if thread is not None:
            thread.queued = []
            await s.commit()
    if not (items and sender and address):
        return
    for item in items:
        results = await send_free_text(sender, address, item["text"])
        ok = bool(results) and all(r.ok for r in results)
        await _set_event(item["call_id"], item["seq"], delivery="sent" if ok else "failed", message_sids=[r.sid for r in results if r.sid])
        await _publish_updated(sender.tenant_id, item["call_id"])


# ---------------------------------------------------------------- status callbacks (WA-07)
async def apply_receipt(params: dict[str, str]) -> bool:
    """Update the `human` event of a message from Twilio's receipt (`MessageSid`, `MessageStatus`, spike S6); True when one matched."""
    sid = (params.get("MessageSid") or params.get("SmsSid") or "").strip()
    state = (params.get("MessageStatus") or params.get("SmsStatus") or "").strip().lower()
    frm, to = (params.get("From") or "").strip(), (params.get("To") or "").strip()
    if not sid or state not in RECEIPT_STATES or not ADDRESS_RE.fullmatch(to):
        return False
    async with sessionmaker()() as s:
        sender = await sender_by_address(s, frm)
        if sender is None:
            return False
        thread = await s.scalar(select(WhatsappThread).where(WhatsappThread.sender_id == sender.id, WhatsappThread.address == to)
                                .order_by(WhatsappThread.created_at.desc()))
        if thread is None or not thread.conversation_id:
            return False
        events = (await s.scalars(select(CallEvent).join(Call, Call.id == CallEvent.call_id)
                                  .where(Call.conversation_id == thread.conversation_id, CallEvent.kind == "human"))).all()
        match = next((e for e in events if sid in ((e.data or {}).get("message_sids") or [])), None)
        if match is None:
            return False
        current = (match.data or {}).get("delivery")
        if state in ("sent", "delivered", "read") and RANK.get(current or "", 0) >= RANK[state]:
            return True  # a late or repeated receipt never moves the state back
        data = {**(match.data or {}), "delivery": state}
        if state in ("failed", "undelivered") and params.get("ErrorCode"):
            data["delivery_error"] = params["ErrorCode"]
        match.data = data
        call_id, tenant_id = match.call_id, match.tenant_id
        await s.commit()
    await _publish_updated(tenant_id, call_id)
    return True


# ---------------------------------------------------------------- resolve, idle, retention
async def thread_closed(tenant_id: str, conv_id: str, assignee: str | None) -> None:
    """WA-13: the specialist resolved the escalation: one closing message if the window is open, the thread ends."""
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, conv_id)
        thread = await thread_of(s, conv) if conv else None
        sender = await s.get(WhatsappSender, thread.sender_id) if thread else None
        if thread is None or sender is None:
            return
        notify = bool(thread.address and thread.status != "opted_out" and window_open(thread))
        address = thread.address
        thread.status, thread.queued = "ended", []
        await s.commit()
    if notify and address:
        first = (assignee or "").split(" ")[0] or "our team"
        await _send_plain(sender, address, f"This conversation has been closed by {first}. Message us again any time.")


async def expire_idle(now: datetime | None = None) -> int:
    """WA-14: a thread with no inbound message for 72 hours and no escalation ends with `end_reason: idle`."""
    from voiceai.runtime.session import AgentSession

    now = now or utcnow()
    async with sessionmaker()() as s:
        stale = (await s.scalars(select(WhatsappThread).where(WhatsappThread.status != "ended", WhatsappThread.last_inbound_at < now - IDLE_AFTER))).all()
        todo = [(t.id, t.tenant_id, t.conversation_id) for t in stale]
    ended = 0
    for thread_id, tenant_id, conv_id in todo:
        async with sessionmaker()() as s:
            conv = await s.get(Conversation, conv_id) if conv_id else None
        if conv is not None and conv.status == "escalated":
            continue  # stays until the specialist resolves it
        if conv is not None and conv.status != "ended":
            if conv.current_call_id:
                session = await AgentSession.open(conv.current_call_id, tenant_id)
                await session.end("idle")
            else:
                await conversations.front_desk_ended(tenant_id, conv.id, "idle")
        async with sessionmaker()() as s:
            row = await s.get(WhatsappThread, thread_id)
            row.status = "ended"
            await s.commit()
        ended += 1
    return ended


async def clear_addresses(now: datetime | None = None) -> int:
    """WA-12: once the conversation ended `WHATSAPP_ADDRESS_RETENTION_DAYS` ago the address is cleared; the last four digits stay."""
    now = now or utcnow()
    cutoff = now - timedelta(days=get_settings().whatsapp_address_retention_days)
    cleared = 0
    async with sessionmaker()() as s:
        for thread in (await s.scalars(select(WhatsappThread).where(WhatsappThread.address.is_not(None)))).all():
            conv = await s.get(Conversation, thread.conversation_id) if thread.conversation_id else None
            if conv is not None:
                ended_at = conv.ended_at if conv.status == "ended" else None
            else:
                ended_at = thread.updated_at if thread.status == "ended" else None
            if ended_at is not None and ended_at < cutoff:
                thread.address, thread.status, thread.queued = None, "ended", []
                cleared += 1
        await s.commit()
    return cleared
