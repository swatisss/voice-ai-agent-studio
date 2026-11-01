"""The /v1 request dependency: key → tenant, path check, scope, request rate limit.

Spec: /api/public-api.md (Tenant resolution and errors, Rate limits), /architecture/multi-tenancy.md (MT-14)
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.models import ApiKey
from voiceai.public import keys

WINDOW_S = 60.0
_hits: dict[str, deque[float]] = {}  # key id -> request times in the window (in process, ADR-0005)


@dataclass
class Client:
    tenant_id: str
    key: ApiKey

    @property
    def scope(self) -> str:
        return self.key.scope


def invalid_key() -> ApiError:
    return ApiError(401, "invalid_key", "Send a valid API key as Authorization: Bearer <key>", {"WWW-Authenticate": "Bearer"})


def tenant_not_found(tenant_id: str) -> ApiError:
    """Identical to an unknown tenant in /api (tenancy.resolve_tenant), so a key never reveals another tenant."""
    return ApiError(404, "tenant_not_found", f"Unknown tenant '{tenant_id}'")


def check_rate(key: ApiKey, now: float | None = None) -> None:
    """PUB-04: a sliding 60 s window per key."""
    now = time.monotonic() if now is None else now
    hits = _hits.setdefault(key.id, deque())
    while hits and hits[0] <= now - WINDOW_S:
        hits.popleft()
    limit = key.rate_limit_per_min
    if len(hits) >= limit:
        retry = max(1, int(hits[0] + WINDOW_S - now) + 1)
        raise ApiError(429, "rate_limited", f"More than {limit} requests in 60 seconds",
                       {"Retry-After": str(retry), "X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"})
    hits.append(now)


def reset_limits() -> None:
    _hits.clear()


async def api_client(tenant_id: str, request: Request, s: AsyncSession = Depends(get_session)) -> Client:
    header = request.headers.get("authorization") or ""
    raw = header[7:].strip() if header.lower().startswith("bearer ") else None
    key = await keys.authenticate(s, raw)
    if key is None:
        raise invalid_key()
    if key.tenant_id != tenant_id:  # MT-14, PUB-02
        raise tenant_not_found(tenant_id)
    check_rate(key)
    request.state.key_prefix = key.prefix
    return Client(tenant_id=key.tenant_id, key=key)
