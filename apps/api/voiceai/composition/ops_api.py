"""Operational endpoints: which models are in use, and whether the service is healthy.

Spec: /api/rest-api.md (Tenants & models, Ops), /architecture/deployment.md (Health)

These belong to the composition root because they report on the wiring itself: the roles the
gateway resolved, and whether each adapter has what it needs. Adding an LLM provider therefore adds
a /healthz key with no change here (LG-13).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.composition.wiring import provider_health
from voiceai.core.config import get_settings
from voiceai.core.db import get_session
from voiceai.core.jobs import worker
from voiceai.core.llm.gateway import gateway

router = APIRouter()


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
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "jobs": worker.alive or not settings.jobs_enabled,
        # LG-13: the providers come from models.yaml, so a new one shows up here by itself
        "providers": provider_health(),
    }
