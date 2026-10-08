"""Tenants, model choices, health and the SSE endpoint.

Spec: /api/rest-api.md (Tenants & models, Ops), /api/events.md, /architecture/deployment.md (Health)
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.config import get_settings
from voiceai.db import get_session
from voiceai.events import bus
from voiceai.jobs import worker
from voiceai.llm.gateway import gateway
from voiceai.models import Tenant
from voiceai.tenancy import resolve_tenant

router = APIRouter()


@router.get("/api/tenants")
async def tenants(s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(Tenant).order_by(Tenant.name))).all()
    return {"items": [{"id": t.id, "name": t.name, "industry": t.industry} for t in rows]}


@router.get("/api/models")
async def models() -> dict:
    g = gateway()
    return {"roles": {r: g.role_model(r) for r in g.roles}, "selectable": g.selectable()}


@router.get("/healthz")
async def healthz(s: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    try:
        await s.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    g = gateway()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "jobs": worker.alive or not settings.jobs_enabled,
        # LG-13: the LLM providers come from models.yaml, so a new one shows up here by itself
        "providers": {
            **{name: g.provider_configured(name) for name in g.providers},
            "deepgram": bool(settings.deepgram_api_key),
        },
    }


@router.get("/api/events")
async def events(request: Request, topics: str = "", tenant: str | None = None, s: AsyncSession = Depends(get_session)) -> StreamingResponse:
    tenant_id = await resolve_tenant(s, tenant or request.headers.get("x-tenant-id"))
    await s.close()
    wanted = {t.strip() for t in topics.split(",") if t.strip()}
    sub = bus.subscribe(tenant_id, wanted)

    async def stream() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(sub.queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
        finally:
            bus.unsubscribe(sub)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
