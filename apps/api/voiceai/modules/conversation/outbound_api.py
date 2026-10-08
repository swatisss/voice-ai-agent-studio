"""Outbound target lists: who an outbound agent may call.

Spec: /api/rest-api.md (Use cases and outbound), /architecture/call-modes.md (Outbound calls)

Placing a call is this module's business, so choosing a callee is too - and the fetch goes through
the same ToolCaller port an agent's tools use, so a target list served by an extracted system needs
no change here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.errors import ApiError
from voiceai.core.tables import Agent, AgentVersion
from voiceai.core.tenancy import current_tenant
from voiceai.core.toolcalling import tool_caller
from voiceai.modules.conversation import outbound

router = APIRouter(prefix="/api")


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
