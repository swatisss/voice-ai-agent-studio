"""Use-case catalog and outbound target lists.

Spec: /api/rest-api.md (Use cases and outbound), /product/use-cases.md, /architecture/call-modes.md
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.errors import ApiError
from voiceai.core.tables import Agent, AgentVersion, UseCase
from voiceai.core.toolcalling import tool_caller
from voiceai.runtime import outbound
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


@router.get("/outbound/targets")
async def outbound_targets(
    agent_id: str, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session),
) -> dict:
    agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    if agent is None:
        raise ApiError(404, "agent_not_found", "Agent not found")
    version = await s.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None
    config = version.config if version else (agent.draft_config or {})
    if config.get("mode") != "outbound":  # OB-05
        raise ApiError(409, "not_outbound", "This agent does not place outbound calls")
    targets = await outbound.fetch_targets((config.get("outbound") or {}).get("targets_url", ""), tool_caller(request.app))
    return {"items": [
        {"member_ref": t["member_ref"], "first_name": t.get("first_name", ""), "summary": t.get("summary", ""), "context": t.get("context") or {}}
        for t in targets
    ]}
