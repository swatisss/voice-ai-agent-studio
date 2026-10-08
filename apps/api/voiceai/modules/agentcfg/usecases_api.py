"""The use-case catalogue: what each agent is for.

Spec: /api/rest-api.md (Use cases and outbound), /product/use-cases.md
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.tables import Agent, UseCase
from voiceai.core.tenancy import current_tenant

router = APIRouter(prefix="/api")


@router.get("/use-cases")
async def use_cases(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(UseCase).where(UseCase.tenant_id == tenant_id).order_by(UseCase.sort))).all()
    agents = {a.id: a for a in (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id))).all()}
    items = []
    for u in rows:
        agent = agents.get(u.agent_id)
        items.append({
            "id": u.id, "category": u.category, "title": u.title, "summary": u.summary, "channels": list(u.channels or []),
            "mode": (agent.draft_config or {}).get("mode", "inbound") if agent else "inbound",
            "agent_id": u.agent_id, "agent_name": agent.name if agent else None,
            "published": bool(agent and agent.published_version_id),
            "sample_utterances": list(u.sample_utterances or []), "demo_callers": list(u.demo_callers or []),
        })
    return {"items": items}
