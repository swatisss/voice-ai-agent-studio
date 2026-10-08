"""The server-sent event stream: one connection per browser tab.

Spec: /api/events.md, /architecture/jobs-and-events.md

Note the `await s.close()` before streaming: the session dependency is released up front because
this generator stays open for the life of the connection. Turning this into a service that holds a
session would leak a database connection per subscriber.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.events import bus
from voiceai.core.tenancy import resolve_tenant

router = APIRouter()


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
