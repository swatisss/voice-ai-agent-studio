"""Twilio helpers: webhook signatures, stream tokens, TwiML, IVR context, call transfer.

Spec: /architecture/telephony.md
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import httpx

from voiceai.config import get_settings

log = logging.getLogger("voiceai.telephony")

TOKEN_TTL_S = 60
IVR_KEY = re.compile(r"^ivr_[a-z0-9_]{1,30}$")
SIP_IVR_HEADER = re.compile(r"^SipHeader_X-IVR-([A-Za-z0-9_-]{1,30})$", re.I)
MAX_IVR_ENTRIES = 10
MAX_IVR_VALUE = 200
NOT_IN_SERVICE = "Sorry, this number is not in service."


# ---------------------------------------------------------------- signatures (TEL-02)
def compute_signature(auth_token: str, url: str, params: Mapping[str, Sequence[str] | str]) -> str:
    """Twilio's scheme: Base64 HMAC-SHA1 over the full URL followed by each POST field name and value, sorted by name."""
    data = url
    for key in sorted(params):
        values = params[key]
        for value in ([values] if isinstance(values, str) else sorted(values)):
            data += key + value
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def valid_signature(auth_token: str, url: str, params: Mapping[str, Sequence[str] | str], signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(compute_signature(auth_token, url, params), signature)


def public_url(path_and_query: str) -> str:
    """The URL Twilio called, rebuilt from PUBLIC_BASE_URL (a tunnel or proxy may have changed the host the app sees)."""
    base = (get_settings().public_base_url or "").rstrip("/")
    return base + path_and_query


def assert_safe_settings() -> None:
    """TEL-10: signature validation can never be switched off on Cloud Run."""
    if not get_settings().twilio_validate_signature and os.environ.get("K_SERVICE"):
        raise RuntimeError("TWILIO_VALIDATE_SIGNATURE=0 is not allowed on Cloud Run: the telephony routes refuse to start")


# ---------------------------------------------------------------- stream tokens (TEL-04)
_used_tokens: dict[str, float] = {}


def _mac(auth_token: str, call_id: str, expires: int) -> str:
    return hmac.new(auth_token.encode(), f"{call_id}.{expires}".encode(), hashlib.sha256).hexdigest()


def mint_token(auth_token: str, call_id: str, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + TOKEN_TTL_S)
    return f"{expires}.{_mac(auth_token, call_id, expires)}"


def consume_token(auth_token: str, call_id: str, token: str | None, now: float | None = None) -> bool:
    """True once for a token minted for this call that has not expired."""
    now = time.time() if now is None else now
    for key in [k for k, exp in _used_tokens.items() if exp < now]:
        _used_tokens.pop(key, None)
    if not token or "." not in token:
        return False
    exp_text, mac = token.split(".", 1)
    try:
        expires = int(exp_text)
    except ValueError:
        return False
    if expires < now or not hmac.compare_digest(_mac(auth_token, call_id, expires), mac) or token in _used_tokens:
        return False
    _used_tokens[token] = expires
    return True


# ---------------------------------------------------------------- IVR context (TEL-05)
def ivr_context(params: Mapping[str, Sequence[str] | str]) -> dict[str, str]:
    """`ivr_<name>` fields (query or form) and SIP headers `X-IVR-<Name>` become call context; at most 10, 200 characters each."""
    found: dict[str, str] = {}
    for key, raw in params.items():
        value = raw if isinstance(raw, str) else (raw[0] if raw else "")
        name = key.lower() if IVR_KEY.match(key.lower()) else None
        header = SIP_IVR_HEADER.match(key)
        if header:
            name = "ivr_" + re.sub(r"[^a-z0-9_]", "_", header.group(1).lower())
        if name and IVR_KEY.match(name) and name not in found:
            found[name] = str(value).strip()[:MAX_IVR_VALUE]
        if len(found) >= MAX_IVR_ENTRIES:
            break
    return found


# ---------------------------------------------------------------- TwiML
def twiml_not_in_service() -> str:
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Say>{escape(NOT_IN_SERVICE)}</Say><Hangup/></Response>"


def twiml_stream(stream_url: str, call_id: str) -> str:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Connect>"
        f"<Stream url={quoteattr(stream_url)}><Parameter name=\"call_id\" value={quoteattr(call_id)}/></Stream>"
        "</Connect><Hangup/></Response>"
    )


def stream_url(call_id: str, token: str) -> str:
    base = (get_settings().public_base_url or "").rstrip("/")
    ws_base = "wss://" + base.split("://", 1)[-1] if base.startswith("https://") else "ws://" + base.split("://", 1)[-1]
    return f"{ws_base}/api/telephony/twilio/stream/{call_id}?token={token}"


def twiml_dial(destination: str) -> str:
    target = f"<Sip>{escape(destination)}</Sip>" if destination.startswith("sip:") else escape(destination)
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Dial>{target}</Dial></Response>"


# ---------------------------------------------------------------- outbound calls (TEL-12..TEL-14)
class TwilioError(Exception):
    """Twilio (or the simulator) refused or could not be reached."""


async def place_call(to: str, from_number: str, twiml: str, timeout_s: int = 30, client: httpx.AsyncClient | None = None) -> str:
    """Ask Twilio to dial `to`; when answered it runs `twiml`. Returns the call SID."""
    s = get_settings()
    url = f"{s.twilio_api_base.rstrip('/')}/2010-04-01/Accounts/{s.twilio_account_sid}/Calls.json"
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(url, data={"To": to, "From": from_number, "Twiml": twiml, "Timeout": str(timeout_s)},
                                 auth=(s.twilio_account_sid or "", s.twilio_auth_token or ""))
        if resp.status_code >= 300:
            raise TwilioError(f"Twilio answered HTTP {resp.status_code}")
        sid = (resp.json() or {}).get("sid")
        if not sid:
            raise TwilioError("Twilio did not return a call SID")
        return str(sid)
    except httpx.HTTPError as exc:
        raise TwilioError(f"cannot reach Twilio: {exc}") from exc
    finally:
        if own:
            await client.aclose()


_expiry_tasks: set[asyncio.Task[None]] = set()


async def close_unanswered(call_id: str, reason: str) -> bool:
    """End a call that never connected: status ended, outcome abandoned, no analysis (TEL-14)."""
    from voiceai.db import sessionmaker, utcnow
    from voiceai.models import Call

    async with sessionmaker()() as db:
        call = await db.get(Call, call_id)
        if call is None or call.ended_at is not None:
            return False
        call.ended_at, call.end_reason, call.status, call.outcome = utcnow(), reason, "ended", "abandoned"
        await db.commit()
    return True


def expire_unanswered(call_id: str, timeout_s: float) -> None:
    """After `timeout_s`, close the call unless its stream connected (TEL-14)."""
    from voiceai.live import LIVE

    async def run() -> None:
        await asyncio.sleep(timeout_s)
        if call_id not in LIVE:
            await close_unanswered(call_id, "hangup")

    task = asyncio.ensure_future(run())
    _expiry_tasks.add(task)
    task.add_done_callback(_expiry_tasks.discard)


# ---------------------------------------------------------------- transfer (TEL-07)
async def transfer_call(call_sid: str, destination: str, client: httpx.AsyncClient | None = None) -> bool:
    """Redirect the live call to `destination` with a Twilio REST update. Never raises; the call ends either way."""
    s = get_settings()
    if not (s.twilio_account_sid and s.twilio_auth_token):
        return False
    url = f"{s.twilio_api_base.rstrip('/')}/2010-04-01/Accounts/{s.twilio_account_sid}/Calls/{call_sid}.json"
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        resp = await client.post(url, data={"Twiml": twiml_dial(destination)}, auth=(s.twilio_account_sid, s.twilio_auth_token))
        if resp.status_code >= 300:
            log.warning("Twilio transfer failed for %s: HTTP %s", call_sid, resp.status_code)
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Twilio transfer failed for %s: %s", call_sid, exc)
        return False
    finally:
        if own:
            await client.aclose()


async def on_phone_end(session: Any, reason: str, call_sid: str, client: httpx.AsyncClient | None = None) -> None:
    """After the closing speech, before the stream closes: redirect an escalated phone call to the agent's transfer number."""
    destination = ((session.config.get("telephony") or {}).get("transfer_to") or "").strip()
    if not (session.state.escalated and destination):
        return
    ok = await transfer_call(call_sid, destination, client)
    note = f"Call transferred to {destination}" if ok else f"Transfer to {destination} failed; the caller was disconnected"
    await session._event("system", note, {"transfer": {"to": destination, "ok": ok}})  # noqa: SLF001
