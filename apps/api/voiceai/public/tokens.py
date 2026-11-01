"""Connect tokens: single-use, bound to tenant, conversation and transport, valid 120 s to open a voice connection.

Spec: /api/public-api.md (Voice connect), /architecture/webrtc-transport.md
"""
from __future__ import annotations

import hashlib
import hmac
import time

from voiceai.config import get_settings

TTL_S = 120
_used: dict[str, float] = {}  # in process, like the Twilio stream tokens (single instance, ADR-0005)


class TokensUnavailable(Exception):
    """PUBLIC_API_SECRET is not set."""


def _secret() -> str:
    secret = get_settings().public_api_secret
    if not secret:
        raise TokensUnavailable("PUBLIC_API_SECRET is not set")
    return secret


def _mac(secret: str, tenant_id: str, conversation_id: str, transport: str, expires: int) -> str:
    msg = f"{tenant_id}.{conversation_id}.{transport}.{expires}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def mint(tenant_id: str, conversation_id: str, transport: str, now: float | None = None) -> tuple[str, int]:
    """(token, expires as unix seconds)."""
    expires = int((time.time() if now is None else now) + TTL_S)
    return f"{expires}.{_mac(_secret(), tenant_id, conversation_id, transport, expires)}", expires


def consume(tenant_id: str, conversation_id: str, transport: str, token: str | None, now: float | None = None) -> bool:
    """True once for an unexpired token minted for exactly this tenant, conversation and transport (PUB-07)."""
    now = time.time() if now is None else now
    for key in [k for k, exp in _used.items() if exp < now]:
        _used.pop(key, None)
    secret = get_settings().public_api_secret
    if not (secret and token and "." in token):
        return False
    exp_text, mac = token.split(".", 1)
    try:
        expires = int(exp_text)
    except ValueError:
        return False
    if expires < now or token in _used:
        return False
    if not hmac.compare_digest(_mac(secret, tenant_id, conversation_id, transport, expires), mac):
        return False
    _used[token] = expires
    return True


SUBPROTOCOL = "vai.voice.v1"
TOKEN_SUBPROTOCOL = "vai-token."


def presented(headers: dict[str, str] | object, subprotocols: list[str]) -> str | None:
    """The token from `Authorization: Bearer` or the `vai-token.<token>` subprotocol; never the query string."""
    auth = getattr(headers, "get", lambda _k, _d=None: None)("authorization", None) or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    for proto in subprotocols:
        if proto.startswith(TOKEN_SUBPROTOCOL):
            return proto[len(TOKEN_SUBPROTOCOL):] or None
    return None
