"""Tenant resolution for every /api request.

Spec: /architecture/multi-tenancy.md
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.errors import ApiError
from voiceai.core.tables import Tenant


async def resolve_tenant(session: AsyncSession, tenant_id: str | None) -> str:
    if not tenant_id:
        raise ApiError(400, "tenant_required", "Send the X-Tenant-Id header (or ?tenant=)")
    exists = await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id))
    if not exists:
        raise ApiError(404, "tenant_not_found", f"Unknown tenant '{tenant_id}'")
    return tenant_id


async def current_tenant(request: Request, session: AsyncSession = Depends(get_session)) -> str:
    tenant_id = request.headers.get("x-tenant-id") or request.query_params.get("tenant")
    return await resolve_tenant(session, tenant_id)
