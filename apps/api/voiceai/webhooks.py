"""Webhooks for public-API conversations: endpoints, signed deliveries, retries, resend and purge.

Spec: /architecture/webhooks.md, /api/rest-api.md (API keys and webhooks)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import string
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs, vault
from voiceai.db import new_id, sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.models import Conversation, WebhookDelivery, WebhookEndpoint

log = logging.getLogger("voiceai.webhooks")

EVENTS = ("conversation.started", "conversation.transferred", "conversation.escalated", "conversation.ended", "conversation.analyzed")
MAX_ENDPOINTS = 5
RETRY_AFTER_S = (10, 60, 300, 1800, 7200, 21600)  # after attempts 1…6; attempt 7 is the last (WH-02)
MAX_ATTEMPTS = len(RETRY_AFTER_S) + 1
TIMEOUT_S = 10
PREVIOUS_SECRET_FOR = timedelta(hours=24)
KEEP_DAYS = 30
SIGNATURE_HEADER = "X-VoiceAI-Signature"
_ALPHABET = string.ascii_letters + string.digits

transport: httpx.AsyncBaseTransport | None = None  # tests install an httpx.MockTransport


def new_secret() -> str:
    return "whsec_" + "".join(secrets.choice(_ALPHABET) for _ in range(32))


def valid_url(url: str) -> bool:
    parts = urlparse(url)
    if not parts.netloc or len(url) > 500:
        return False
    if parts.scheme == "https":
        return True
    local = (parts.hostname or "") in ("localhost", "127.0.0.1")
    return parts.scheme == "http" and local and not os.environ.get("K_SERVICE")


def check_events(events: list[str]) -> list[str]:
    unknown = [e for e in events if e not in EVENTS]
    if not events or unknown:
        raise ApiError(422, "invalid_events", "Choose one or more of: " + ", ".join(EVENTS))
    return list(dict.fromkeys(events))


def out(e: WebhookEndpoint) -> dict[str, Any]:
    return {"id": e.id, "url": e.url, "events": e.events, "include_transcript": e.include_transcript, "enabled": e.enabled,
            "created_at": e.created_at.isoformat(), "secret_rotated_at": e.secret_rotated_at.isoformat() if e.secret_rotated_at else None}


def delivery_out(d: WebhookDelivery) -> dict[str, Any]:
    return {"id": d.id, "event_id": d.event_id, "type": d.type, "conversation_id": d.conversation_id, "status": d.status,
            "attempts": d.attempts, "last_status_code": d.last_status_code, "last_error": d.last_error,
            "created_at": d.created_at.isoformat(), "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None}


def _encrypt(secret: str) -> str:
    try:
        return vault.encrypt(secret)
    except vault.VaultUnavailable as exc:
        raise ApiError(503, "secrets_unavailable", "Secret storage is not configured on this server (TENANT_SECRETS_KEY)") from exc


async def create_endpoint(s: AsyncSession, tenant_id: str, url: str, events: list[str], include_transcript: bool, enabled: bool) -> tuple[WebhookEndpoint, str]:
    if not valid_url(url):
        raise ApiError(422, "invalid_url", "Use an https:// URL")
    events = check_events(events)
    count = await s.scalar(select(func.count()).select_from(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant_id))
    if (count or 0) >= MAX_ENDPOINTS:
        raise ApiError(409, "too_many_endpoints", f"A business unit can have at most {MAX_ENDPOINTS} webhook endpoints")
    secret = new_secret()
    row = WebhookEndpoint(tenant_id=tenant_id, url=url, events=events, include_transcript=include_transcript, enabled=enabled,
                          secret_ciphertext=_encrypt(secret))
    s.add(row)
    await s.flush()
    return row, secret


def rotate(row: WebhookEndpoint) -> str:
    """WH-04: a new secret; the previous one keeps signing for 24 h."""
    secret = new_secret()
    row.previous_secret_ciphertext, row.secret_ciphertext = row.secret_ciphertext, _encrypt(secret)
    row.secret_rotated_at = utcnow()
    return secret


def sign(secret: str, body: bytes, ts: int) -> str:
    return hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def signature_header(endpoint: WebhookEndpoint, body: bytes, ts: int, now=None) -> str | None:  # noqa: ANN001
    secret = vault.decrypt(endpoint.secret_ciphertext)
    if secret is None:
        return None
    parts = [f"t={ts}", f"v1={sign(secret, body, ts)}"]
    rotated = endpoint.secret_rotated_at
    if endpoint.previous_secret_ciphertext and rotated and (now or utcnow()) - rotated < PREVIOUS_SECRET_FOR:
        previous = vault.decrypt(endpoint.previous_secret_ciphertext)
        if previous:
            parts.append(f"v1={sign(previous, body, ts)}")
    return ",".join(parts)


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), default=str).encode()


async def emit(s: AsyncSession, conv: Conversation, type_: str, data: dict[str, Any], transcript: list[dict[str, Any]] | None = None) -> int:
    """Queue one delivery per enabled endpoint subscribed to the event, for API conversations only (WH-01). Caller commits."""
    if conv.source != "api":
        return 0
    endpoints = (await s.scalars(select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == conv.tenant_id, WebhookEndpoint.enabled.is_(True)))).all()
    event_id = "evt_" + new_id()
    base = {"conversation_id": conv.id, "external_id": conv.external_id, "metadata": conv.metadata_ or {}, **data}
    n = 0
    for ep in endpoints:
        if type_ not in (ep.events or []):
            continue
        body = dict(base)
        if type_ == "conversation.analyzed" and ep.include_transcript and transcript is not None:  # WH-03
            body["transcript"] = transcript
        payload = {"id": event_id, "type": type_, "created_at": utcnow().isoformat(), "tenant_id": conv.tenant_id, "data": body}
        row = WebhookDelivery(tenant_id=conv.tenant_id, endpoint_id=ep.id, event_id=event_id, type=type_, conversation_id=conv.id,
                              payload=payload, next_attempt_at=utcnow())
        s.add(row)
        await s.flush()
        await jobs.enqueue(s, conv.tenant_id, "deliver_webhook", {"delivery_id": row.id})
        n += 1
    return n


async def resend(s: AsyncSession, row: WebhookDelivery) -> WebhookDelivery:
    """WH-05: one fresh attempt with the same event id."""
    row.status, row.next_attempt_at = "pending", utcnow()
    await jobs.enqueue(s, row.tenant_id, "deliver_webhook", {"delivery_id": row.id, "resend": True})
    return row


@jobs.register("deliver_webhook")
async def deliver(tenant_id: str, payload: dict[str, Any]) -> None:
    """One attempt; failures schedule the next attempt as a new job instead of the queue's own retry (WH-02)."""
    async with sessionmaker()() as s:
        row = await s.scalar(select(WebhookDelivery).where(WebhookDelivery.id == payload["delivery_id"], WebhookDelivery.tenant_id == tenant_id))
        if row is None or row.status == "delivered" and not payload.get("resend"):
            return
        endpoint = await s.get(WebhookEndpoint, row.endpoint_id)
        if endpoint is None:
            row.status, row.last_error = "failed", "endpoint deleted"
            await s.commit()
            return
        body = encode(row.payload)
        ts = int(time.time())
        header = signature_header(endpoint, body, ts)
        row.attempts += 1
        code: int | None = None
        error: str | None = None
        if header is None:
            error = "secret cannot be decrypted (TENANT_SECRETS_KEY)"
        else:
            try:
                async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S, follow_redirects=False) as client:
                    resp = await client.post(endpoint.url, content=body, headers={
                        "Content-Type": "application/json", SIGNATURE_HEADER: header, "User-Agent": "VoiceAI-Webhooks/1"})
                code = resp.status_code
                if not 200 <= code < 300:
                    error = f"HTTP {code}"
            except httpx.HTTPError as exc:
                error = type(exc).__name__
        row.last_status_code, row.last_error = code, error
        if error is None:
            row.status, row.delivered_at, row.next_attempt_at = "delivered", utcnow(), None
        elif payload.get("resend") or row.attempts >= MAX_ATTEMPTS:
            row.status, row.next_attempt_at = "failed", None
        else:
            row.status = "pending"
            row.next_attempt_at = utcnow() + timedelta(seconds=RETRY_AFTER_S[min(row.attempts, len(RETRY_AFTER_S)) - 1])
            await jobs.enqueue(s, tenant_id, "deliver_webhook", {"delivery_id": row.id}, run_after=row.next_attempt_at)
        await s.commit()


async def purge_old(days: int = KEEP_DAYS) -> int:
    async with sessionmaker()() as s:
        res = await s.execute(delete(WebhookDelivery).where(WebhookDelivery.created_at < utcnow() - timedelta(days=days)))
        await s.commit()
        return res.rowcount or 0
