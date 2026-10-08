"""The dashboard endpoint.

Spec: /ui/dashboard.md, /api/rest-api.md (Dashboard)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.tenancy import current_tenant
from voiceai.modules.analytics.service import summary as dashboard_summary

router = APIRouter(prefix="/api/dashboard")


@router.get("/summary")
async def summary(
    agent_id: str | None = None, tenant_id: str = Depends(current_tenant),
    s: AsyncSession = Depends(get_session),
) -> dict:
    return await dashboard_summary(s, tenant_id, agent_id)
