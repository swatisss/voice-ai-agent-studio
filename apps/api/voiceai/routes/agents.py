"""Agents, versions, scenarios, tools and skills.

Spec: /api/rest-api.md (Agents; Tools, skills), /data/agent-config.md
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.agents import agent_out, default_config, publish, skill_dict, tool_dict, validate_config
from voiceai.core.db import get_session
from voiceai.core.errors import ApiError
from voiceai.core.tables import Agent, AgentVersion, EvalScenario, Skill, Tool
from voiceai.schemas import SkillDef, ToolDef
from voiceai.core.tenancy import current_tenant

router = APIRouter(prefix="/api")


async def _agent(s: AsyncSession, tenant_id: str, agent_id: str) -> Agent:
    agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    if not agent:  # MT-01
        raise ApiError(404, "agent_not_found", "Agent not found")
    return agent


async def _version(s: AsyncSession, agent: Agent) -> AgentVersion | None:
    return await s.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    draft_config: dict[str, Any] | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    draft_config: dict[str, Any] | None = None


class PublishBody(BaseModel):
    change_note: str = ""


@router.get("/agents")
async def list_agents(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agents = (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id).order_by(Agent.created_at))).all()
    items = []
    for a in agents:
        items.append(agent_out(a, await _version(s, a)))
    return {"items": items}


@router.post("/agents")
async def create_agent(body: AgentCreate, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    cfg = validate_config(body.draft_config or default_config())
    agent = Agent(tenant_id=tenant_id, name=body.name, description=body.description, draft_config=cfg)
    s.add(agent)
    await s.commit()
    return agent_out(agent, None)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = await _agent(s, tenant_id, agent_id)
    return agent_out(agent, await _version(s, agent))


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = await _agent(s, tenant_id, agent_id)
    if body.name is not None:
        agent.name = body.name
    if body.description is not None:
        agent.description = body.description
    if body.draft_config is not None:
        agent.draft_config = validate_config(body.draft_config)
    await s.commit()
    return agent_out(agent, await _version(s, agent))


@router.post("/agents/{agent_id}/publish")
async def publish_agent(agent_id: str, body: PublishBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = await _agent(s, tenant_id, agent_id)
    version = await publish(s, agent, body.change_note)
    await s.commit()
    return {"id": version.id, "version": version.version, "created_at": version.created_at.isoformat()}


@router.get("/agents/{agent_id}/versions")
async def versions(agent_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await _agent(s, tenant_id, agent_id)
    rows = (await s.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()))).all()
    return {"items": [{"id": v.id, "version": v.version, "change_note": v.change_note, "source_proposal_id": v.source_proposal_id,
                       "created_at": v.created_at.isoformat()} for v in rows]}


@router.get("/agents/{agent_id}/scenarios")
async def scenarios(agent_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await _agent(s, tenant_id, agent_id)
    rows = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == agent_id))).all()
    return {"items": [{"id": r.id, "name": r.name, "caller_goal": r.caller_goal, "caller_profile": r.caller_profile, "expected": r.expected} for r in rows]}


# ---------------------------------------------------------------- tools
@router.get("/tools")
async def list_tools(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(Tool).where(Tool.tenant_id == tenant_id).order_by(Tool.name))).all()
    return {"items": [{**tool_dict(t), "status": t.status} for t in rows]}


@router.post("/tools")
async def create_tool(body: ToolDef, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    tool = Tool(tenant_id=tenant_id, **body.model_dump())
    s.add(tool)
    try:
        await s.commit()
    except IntegrityError as exc:
        raise ApiError(409, "duplicate_tool", f"A tool named '{body.name}' already exists") from exc
    return tool_dict(tool)


@router.put("/tools/{tool_id}")
async def update_tool(tool_id: str, body: ToolDef, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    tool = await s.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id))
    if not tool:
        raise ApiError(404, "tool_not_found", "Tool not found")
    for k, v in body.model_dump().items():
        setattr(tool, k, v)
    await s.commit()
    return tool_dict(tool)


@router.delete("/tools/{tool_id}", status_code=204)
async def delete_tool(tool_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    tool = await s.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id))
    if not tool:
        raise ApiError(404, "tool_not_found", "Tool not found")
    await s.delete(tool)
    await s.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- skills
@router.get("/skills")
async def list_skills(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(Skill).where(Skill.tenant_id == tenant_id).order_by(Skill.name))).all()
    return {"items": [{**skill_dict(k), "status": k.status} for k in rows]}


@router.post("/skills")
async def create_skill(body: SkillDef, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    skill = Skill(tenant_id=tenant_id, **body.model_dump())
    s.add(skill)
    await s.commit()
    return skill_dict(skill)


@router.put("/skills/{skill_id}")
async def update_skill(skill_id: str, body: SkillDef, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    skill = await s.scalar(select(Skill).where(Skill.id == skill_id, Skill.tenant_id == tenant_id))
    if not skill:
        raise ApiError(404, "skill_not_found", "Skill not found")
    for k, v in body.model_dump().items():
        setattr(skill, k, v)
    await s.commit()
    return skill_dict(skill)


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    skill = await s.scalar(select(Skill).where(Skill.id == skill_id, Skill.tenant_id == tenant_id))
    if not skill:
        raise ApiError(404, "skill_not_found", "Skill not found")
    await s.delete(skill)
    await s.commit()
    return Response(status_code=204)
