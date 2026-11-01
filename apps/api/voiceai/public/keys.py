"""API keys: generation, hashing, lookup, limits and revocation.

Spec: /api/public-api.md (API keys), /architecture/multi-tenancy.md (rule 9)
"""
from __future__ import annotations

import hashlib
import secrets
import string
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import utcnow
from voiceai.errors import ApiError
from voiceai.models import ApiKey

PREFIX = "vak_"
BODY_LEN = 40
DISPLAY_LEN = 12
MAX_ACTIVE = 20
SCOPES = ("member", "staff")
SCOPE_MODE = {"member": "inbound", "staff": "internal"}  # outbound agents are never reachable
TOUCH_EVERY = timedelta(minutes=1)
_ALPHABET = string.ascii_letters + string.digits


def generate() -> str:
    """`vak_` + 40 random base62 characters (about 238 bits)."""
    return PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(BODY_LEN))


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def well_formed(raw: str | None) -> bool:
    return bool(raw) and raw.startswith(PREFIX) and len(raw) == len(PREFIX) + BODY_LEN and raw[len(PREFIX):].isalnum()


def out(k: ApiKey) -> dict[str, Any]:
    return {
        "id": k.id, "name": k.name, "prefix": k.prefix, "scope": k.scope, "rate_limit_per_min": k.rate_limit_per_min,
        "max_concurrent_voice": k.max_concurrent_voice, "created_at": k.created_at.isoformat(),
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
    }


async def create(s: AsyncSession, tenant_id: str, name: str, scope: str, rate_limit_per_min: int, max_concurrent_voice: int) -> tuple[ApiKey, str]:
    """A new key; the plain key is returned once and never stored (PUB-01)."""
    if await s.scalar(select(ApiKey.id).where(ApiKey.tenant_id == tenant_id, ApiKey.name == name)):
        raise ApiError(409, "name_taken", f"A key named '{name}' already exists")
    active = await s.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.tenant_id == tenant_id, ApiKey.revoked_at.is_(None)))
    if (active or 0) >= MAX_ACTIVE:  # API-10
        raise ApiError(409, "too_many_keys", f"A business unit can have at most {MAX_ACTIVE} active keys")
    raw = generate()
    row = ApiKey(tenant_id=tenant_id, name=name, prefix=raw[:DISPLAY_LEN], key_hash=hash_key(raw), scope=scope,
                 rate_limit_per_min=rate_limit_per_min, max_concurrent_voice=max_concurrent_voice)
    s.add(row)
    await s.flush()
    return row, raw


async def authenticate(s: AsyncSession, raw: str | None) -> ApiKey | None:
    """The active key for a presented secret, or None (missing, malformed, unknown or revoked: PUB-02)."""
    if not raw or not well_formed(raw):
        return None
    row = await s.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw)))
    if row is None or row.revoked_at is not None:
        return None
    now = utcnow()
    if row.last_used_at is None or now - row.last_used_at >= TOUCH_EVERY:  # at most once a minute
        row.last_used_at = now
        await s.commit()
    return row
