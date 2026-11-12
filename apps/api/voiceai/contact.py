"""Contact tools: send the caller details by email (Brevo), SMS or a message call (Twilio), or into the outbox.

Spec: /architecture/contact-tools.md

Every agent offers `send_email`, `send_sms` and `place_call`. A tool first returns the address to read back
(`confirmed: false`), then sends (`confirmed: true`). The registered contact comes from the business API at that
moment and is never stored or shown unmasked; simulations and evaluations never deliver.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

import httpx

from voiceai.config import Settings, get_settings
from voiceai.db import sessionmaker
from voiceai.models import ContactMessage
from voiceai.runtime import language
from voiceai.runtime.state import CallState

log = logging.getLogger("voiceai.contact")

CHANNEL_OF = {"send_email": "email", "send_sms": "sms", "place_call": "call"}
TOOL_NAMES = frozenset(CHANNEL_OF)
MESSAGE_MAX = {"email": 2000, "sms": 480, "call": 600}
SUBJECT_MAX = 120
MAX_PER_CALL = 3  # CT-07
TIMEOUT_S = 10

# Tests replace this with an httpx.MockTransport; no unit test reaches a real provider.
TRANSPORT: httpx.AsyncBaseTransport | None = None

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")  # + then 8-15 digits
_PHONE_JUNK = re.compile(r"[\s\-.()]")

SAY_INVALID_EMAIL = "That email address doesn't look complete. Could you say it again?"
SAY_INVALID_PHONE = "Could you give me that number again, with the country code?"
SAY_NO_EMAIL = "There's no email address on your record. Which address should I use?"
SAY_NO_PHONE = "There's no mobile number on your record. Which number should I use?"
SAY_LIMIT = "I can't send any more messages on this call."
SAY_FAILED = "I couldn't send that just now."
REPEAT_EN = "Here is the message again."
REPEAT_HI = "संदेश फिर से सुनिए।"


def _schema(name: str, description: str, to_help: str, subject: bool, limit: int) -> dict[str, Any]:
    props: dict[str, Any] = {
        "to": {"type": "string", "description": to_help},
        "message": {"type": "string", "description": f"The details to send, short and plain, in the caller's language (max {limit} characters)"},
        "confirmed": {"type": "boolean", "description": "false first, to get the address to read back; true only after the caller said yes to that exact address"},
    }
    required = ["to", "message", "confirmed"]
    if subject:
        props = {"to": props["to"], "subject": {"type": "string", "description": f"Short subject line (max {SUBJECT_MAX} characters)"}, **{k: v for k, v in props.items() if k != "to"}}
        required = ["to", "subject", "message", "confirmed"]
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": props, "required": required}}}


SCHEMAS: list[dict[str, Any]] = [  # CT-01: on every agent, every channel
    _schema("send_email", "Email the caller details they want to keep, such as a document list, reference number or claim update.",
            '"registered" for the email on the verified member\'s record, or an email address the caller gave', True, MESSAGE_MAX["email"]),
    _schema("send_sms", "Text the caller details they want to keep.",
            '"registered" for the mobile number on the verified member\'s record, or a phone number with country code', False, MESSAGE_MAX["sms"]),
    _schema("place_call", "Phone the caller with an automated call that reads the details aloud twice and hangs up.",
            '"registered" for the mobile number on the verified member\'s record, or a phone number with country code', False, MESSAGE_MAX["call"]),
]


# ------------------------------------------------------------------ addresses
def normalise_phone(raw: str) -> str | None:
    """CT-05: spaces, dashes, dots and brackets removed; E.164 or None."""
    phone = _PHONE_JUNK.sub("", language.normalise_text(raw or ""))
    return phone if _E164.match(phone) else None


def normalise_email(raw: str) -> str | None:
    email = (raw or "").strip().lower()
    return email if len(email) <= 254 and _EMAIL.match(email) else None


def mask(channel: str, address: str) -> str:
    if channel == "email":
        local, _, domain = address.partition("@")
        return f"{local[:1]}***@{domain}"
    return f"***{address[-4:]}"


# ------------------------------------------------------------------ providers
def provider_of(channel: str, settings: Settings | None = None) -> str:
    """The provider this channel uses now: the explicit setting, otherwise chosen from the keys, otherwise the outbox."""
    s = settings or get_settings()
    explicit = {"email": s.email_provider, "sms": s.sms_provider, "call": s.call_provider}[channel]
    if explicit and explicit.strip():
        return explicit.strip().lower()
    if channel == "email":
        return "brevo" if s.brevo_api_key and s.email_from else "outbox"
    return "twilio" if _twilio_ready(s) else "outbox"


def _twilio_ready(s: Settings) -> bool:
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number)


@dataclass
class Delivery:
    status: str  # sent | outbox | simulated | failed
    provider: str
    provider_ref: str | None = None
    error: str | None = None


def twiml(message: str) -> str:
    """CT-09: read the message, pause, say it is repeated, read it again; Hindi messages use a Hindi voice."""
    if language.has_devanagari(message):
        say, repeat = '<Say language="hi-IN" voice="Polly.Aditi">', REPEAT_HI
    else:
        say, repeat = '<Say language="en-US">', REPEAT_EN
    body = escape(message)
    return f'<Response>{say}{body}</Say><Pause length="1"/>{say}{repeat}</Say>{say}{body}</Say></Response>'


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_S)


def _failure(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("message") or body.get("code") or ""
    except ValueError:
        detail = resp.text
    return f"http_{resp.status_code}: {detail}"[:300]


async def _brevo(s: Settings, to: str, subject: str, body: str, sender_name: str) -> Delivery:
    if not (s.brevo_api_key and s.email_from):
        return Delivery("failed", "brevo", error="not_configured")
    payload = {"sender": {"email": s.email_from, "name": s.email_from_name or sender_name}, "to": [{"email": to}],
               "subject": subject, "textContent": body}
    headers = {"api-key": s.brevo_api_key, "accept": "application/json", "content-type": "application/json"}
    async with _client() as client:
        resp = await client.post(f"{s.brevo_api_base.rstrip('/')}/v3/smtp/email", json=payload, headers=headers)
    if resp.is_success:
        return Delivery("sent", "brevo", provider_ref=str(resp.json().get("messageId") or "") or None)
    return Delivery("failed", "brevo", error=_failure(resp))


async def _twilio(s: Settings, channel: str, to: str, body: str) -> Delivery:
    if not _twilio_ready(s):
        return Delivery("failed", "twilio", error="not_configured")
    resource = "Messages" if channel == "sms" else "Calls"
    form = {"To": to, "From": s.twilio_from_number or ""}
    if channel == "sms":
        form["Body"] = body
    else:
        form["Twiml"] = twiml(body)
    url = f"{s.twilio_api_base.rstrip('/')}/2010-04-01/Accounts/{s.twilio_account_sid}/{resource}.json"
    async with _client() as client:
        resp = await client.post(url, data=form, auth=(s.twilio_account_sid or "", s.twilio_auth_token or ""))
    if resp.is_success:
        return Delivery("sent", "twilio", provider_ref=str(resp.json().get("sid") or "") or None)
    return Delivery("failed", "twilio", error=_failure(resp))


async def deliver(channel: str, to: str, subject: str, body: str, sender_name: str) -> Delivery:
    """Send through the channel's provider (CT-08, CT-09) or keep it in the outbox (CT-10)."""
    s = get_settings()
    provider = provider_of(channel, s)
    try:
        if provider == "outbox":
            return Delivery("outbox", "outbox")
        if channel == "email" and provider == "brevo":
            return await _brevo(s, to, subject, body, sender_name)
        if channel in ("sms", "call") and provider == "twilio":
            return await _twilio(s, channel, to, body)
        return Delivery("failed", provider[:16], error="not_configured")
    except httpx.TimeoutException:
        return Delivery("failed", provider[:16], error="timeout")
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("%s delivery failed: %s", channel, exc)
        return Delivery("failed", provider[:16], error=f"connection_error: {str(exc)[:200]}")


# ------------------------------------------------------------------ the tools
async def registered_contact(member_ref: str, tenant_id: str, call_id: str, app: Any | None = None) -> dict[str, Any] | None:  # noqa: ANN401
    """The contact on the member's record, read at sending time and never stored (MOCK-18)."""
    from voiceai.runtime.tools import business_client

    url = get_settings().member_contact_url
    headers = {"X-Member-Ref": member_ref, "X-Tenant-Id": tenant_id, "X-Call-Id": call_id}
    try:
        async with business_client(url.startswith(("http://", "https://")), app) as client:
            resp = await client.get(url, headers=headers, timeout=5)
        return resp.json() if resp.status_code < 400 else None
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("contact lookup failed: %s", exc)
        return None


def _confirmed(value: Any) -> bool:  # noqa: ANN401
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


class ContactTools:
    """Runs the three contact tools for one call; the caller of `run` owns the tool-error streak."""

    def __init__(self, tenant_id: str, call_id: str, agent_id: str, state: CallState, *, tenant_name: str = "",
                 simulated: bool = False, app: Any | None = None) -> None:  # noqa: ANN401
        self.tenant_id = tenant_id
        self.call_id = call_id
        self.agent_id = agent_id
        self.state = state
        self.tenant_name = tenant_name
        self.simulated = simulated
        self.app = app

    def _used(self, name: str, ok: bool, summary: str) -> None:
        self.state.tools_used.append({"name": name, "ok": ok, "summary": summary[:160]})

    async def run(self, name: str, args: dict[str, Any], verify_say: str) -> tuple[dict[str, Any], bool]:
        """Returns (result, ok). ok=False only for a failed delivery or contact lookup (ES-03)."""
        channel = CHANNEL_OF[name]
        to = str(args.get("to") or "").strip()
        message = str(args.get("message") or "").strip()
        subject = str(args.get("subject") or "").strip() if channel == "email" else ""
        # 1. arguments
        if not to or not message or (channel == "email" and not subject):
            self._used(name, False, f"{name}: invalid_arguments")
            return {"error": "invalid_arguments", "detail": "Give to, message" + (", subject" if channel == "email" else "") + " and confirmed."}, True
        if len(message) > MESSAGE_MAX[channel] or len(subject) > SUBJECT_MAX:
            self._used(name, False, f"{name}: message_too_long")
            return {"error": "message_too_long", "detail": f"Keep the message under {MESSAGE_MAX[channel]} characters"
                    + (f" and the subject under {SUBJECT_MAX}" if channel == "email" else "") + "."}, True
        registered = to.lower() == "registered"
        if registered:
            # 2. the contact on file: verified calls only, read now, never stored (CT-02, CT-03, CT-04)
            if not (self.state.verified and self.state.verified_member_ref):
                self._used(name, False, f"{name}: blocked until identity verified")
                return {"error": "identity_not_verified", "say": verify_say}, True
            contact = await registered_contact(self.state.verified_member_ref, self.tenant_id, self.call_id, self.app)
            if contact is None:
                self._used(name, False, f"{name}: contact lookup failed")
                return {"error": "contact_unavailable"}, False
            raw = contact.get("email") if channel == "email" else contact.get("mobile")
            address = (normalise_email(raw) if channel == "email" else normalise_phone(raw)) if raw else None
            if not address:
                error, say = ("no_registered_email", SAY_NO_EMAIL) if channel == "email" else ("no_registered_phone", SAY_NO_PHONE)
                self._used(name, False, f"{name}: {error}")
                return {"error": error, "say": say}, True
        else:
            address = normalise_email(to) if channel == "email" else normalise_phone(to)
            if not address:
                error, say = ("invalid_email", SAY_INVALID_EMAIL) if channel == "email" else ("invalid_phone", SAY_INVALID_PHONE)
                self._used(name, False, f"{name}: {error}")
                return {"error": error, "say": say}, True
        masked = mask(channel, address)
        # 3. content guard: never the member ID (CT-06)
        ref = (self.state.verified_member_ref or "").lower()
        if ref and (ref in message.lower() or ref in subject.lower()):
            self._used(name, False, f"{name}: member_id_in_message")
            return {"error": "member_id_in_message", "detail": "Leave the member ID out of the message and send again."}, True
        if not _confirmed(args.get("confirmed")):
            shown = masked if registered else address
            if not registered:
                say = f"Just to confirm, that's {address}?"
            elif channel == "email":
                say = f"Shall I send it to your email on file, {masked}?"
            else:
                say = f"Shall I {'text' if channel == 'sms' else 'call'} your mobile number ending {address[-4:]}?"
            self._used(name, True, f"{name}: asked to confirm {masked}")
            return {"status": "needs_confirmation", "channel": channel, "to": shown, "say": say}, True
        # 4. at most three per call (CT-07)
        if self.state.messages_sent >= MAX_PER_CALL:
            self._used(name, False, f"{name}: message_limit")
            return {"error": "message_limit", "say": SAY_LIMIT}, True
        self.state.messages_sent += 1
        # 5. deliver: never from a simulation (CT-10); redirect for testing (CT-11)
        redirected = False
        target, sent_subject = address, subject
        if self.simulated:
            outcome = Delivery("simulated", "simulated")
        else:
            s = get_settings()
            redirect = s.contact_redirect_email if channel == "email" else s.contact_redirect_phone
            redirect = (normalise_email(redirect) if channel == "email" else normalise_phone(redirect)) if redirect else None
            if redirect and provider_of(channel, s) != "outbox":
                target, redirected = redirect, True
                if channel == "email":
                    sent_subject = f"[for {masked}] {subject}"
            outcome = await deliver(channel, target, sent_subject, message, self.tenant_name or "Echo Mind")
        # 6. record, masked (DM-15)
        await self._record(channel, "registered" if registered else "other", masked, subject or None, message, outcome, redirected)
        if outcome.status == "failed":
            self._used(name, False, f"{name}: failed ({(outcome.error or '')[:60]})")
            return {"error": "delivery_failed", "say": SAY_FAILED}, False
        self._used(name, True, f"{name}: sent to {masked}" + ("" if outcome.status == "sent" else f" ({outcome.status})"))
        return {"status": "sent", "channel": channel, "to": masked}, True

    async def _record(self, channel: str, destination: str, masked: str, subject: str | None, body: str,
                      outcome: Delivery, redirected: bool) -> None:
        async with sessionmaker()() as s:
            s.add(ContactMessage(tenant_id=self.tenant_id, call_id=self.call_id, agent_id=self.agent_id, seq=self.state.messages_sent, channel=channel,
                                 destination=destination, to_masked=masked, subject=subject, body=body,
                                 provider=outcome.provider, status=outcome.status, provider_ref=outcome.provider_ref,
                                 error=outcome.error, redirected=redirected))
            await s.commit()


def health() -> dict[str, str]:
    """DEP-06: the provider each channel would use now; no network call."""
    return {channel: provider_of(channel) for channel in ("email", "sms", "call")}
