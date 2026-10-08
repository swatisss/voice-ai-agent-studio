"""The tenant list: which tenants this deployment serves.

Spec: /api/rest-api.md (Tenants & models), /architecture/multi-tenancy.md

v1 has no authentication and the web app's tenant switcher stands in for login, so this endpoint is
the one that does not itself require a tenant.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.tables import Tenant

router = APIRouter()


@router.get("/api/tenants")
async def tenants(s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(Tenant).order_by(Tenant.name))).all()
    return {"items": [{"id": t.id, "name": t.name, "industry": t.industry} for t in rows]}
