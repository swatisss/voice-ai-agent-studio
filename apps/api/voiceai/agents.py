"""Agent config validation, snapshots and publishing.

Spec: /data/agent-config.md, /architecture/multi-tenancy.md (rule 3), /architecture/tools-and-skills.md (TS-07)
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.errors import ApiError
from voiceai.core.events import bus
from voiceai.core.llm.gateway import gateway
from voiceai.live import persona_dict
from voiceai.core.tables import Agent, AgentVersion, KnowledgeDoc, Persona, Skill, Tool
from voiceai.schemas import AgentConfig


def default_config() -> dict[str, Any]:
    return AgentConfig().model_dump()


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        cfg = AgentConfig.model_validate(raw)
    except ValidationError as exc:  # DM-04
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", []))
        msg = str(first.get("msg", "")).removeprefix("Value error, ")
        raise ApiError(422, "invalid_config", f"{loc}: {msg}" if loc else msg) from exc
    if cfg.models.realtime and cfg.models.realtime not in gateway().selectable():
        raise ApiError(422, "invalid_config", f"Unknown model '{cfg.models.realtime}'")
    return cfg.model_dump()


def tool_dict(t: Tool) -> dict[str, Any]:
    return {
        "id": t.id, "name": t.name, "description": t.description, "method": t.method, "url": t.url,
        "parameters": t.parameters, "requires_verification": t.requires_verification,
        "is_verification": t.is_verification, "timeout_s": t.timeout_s,
    }


def skill_dict(s: Skill) -> dict[str, Any]:
    return {
        "id": s.id, "name": s.name, "description": s.description, "instructions": s.instructions,
        "required_tools": list(s.required_tools or []), "escalate_when": s.escalate_when,
    }


async def build_snapshot(s: AsyncSession, tenant_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Resolve ids into a self-contained, immutable config (DM-05); validate references (MT-03, TS-07)."""
    cfg = validate_config(draft)
    tools = list((await s.scalars(select(Tool).where(Tool.tenant_id == tenant_id, Tool.id.in_(cfg["tool_ids"])))).all())
    skills = list((await s.scalars(select(Skill).where(Skill.tenant_id == tenant_id, Skill.id.in_(cfg["skill_ids"])))).all())
    docs = list((await s.scalars(select(KnowledgeDoc.id).where(
        KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.id.in_(cfg["knowledge_doc_ids"]), KnowledgeDoc.status != "archived",
    ))).all())
    missing = (
        set(cfg["tool_ids"]) - {t.id for t in tools}
        | set(cfg["skill_ids"]) - {k.id for k in skills}
        | set(cfg["knowledge_doc_ids"]) - set(docs)
    )
    if missing:
        raise ApiError(422, "invalid_reference", f"Config references unknown or archived objects: {', '.join(sorted(missing))}")
    tool_names = {t.name for t in tools}
    for sk in skills:
        absent = [n for n in (sk.required_tools or []) if n not in tool_names and n != "search_knowledge"]
        if absent:
            raise ApiError(422, "missing_tool", f"Skill '{sk.name}' requires tool(s) not attached to this agent: {', '.join(absent)}")
    persona = cfg["persona"]
    if cfg.get("persona_id"):
        row = await s.scalar(select(Persona).where(Persona.id == cfg["persona_id"], Persona.tenant_id == tenant_id))
        if row is None:
            raise ApiError(422, "invalid_reference", f"Config references an unknown persona: {cfg['persona_id']}")
        persona = persona_dict(row)
    order_t = {i: n for n, i in enumerate(cfg["tool_ids"])}
    order_s = {i: n for n, i in enumerate(cfg["skill_ids"])}
    return {
        **cfg,
        "persona": persona,
        "tools": [tool_dict(t) for t in sorted(tools, key=lambda t: order_t[t.id])],
        "skills": [skill_dict(k) for k in sorted(skills, key=lambda k: order_s[k.id])],
    }


async def publish(
    s: AsyncSession, agent: Agent, change_note: str = "", source_proposal_id: str | None = None,
) -> AgentVersion:
    snapshot = await build_snapshot(s, agent.tenant_id, agent.draft_config or {})
    current = await s.scalar(select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent.id)) or 0
    version = AgentVersion(
        tenant_id=agent.tenant_id, agent_id=agent.id, version=current + 1, config=snapshot,
        change_note=change_note or f"Version {current + 1}", source_proposal_id=source_proposal_id,
    )
    s.add(version)
    await s.flush()
    agent.published_version_id = version.id
    payload = {"agent_id": agent.id, "version_id": version.id, "version": version.version}
    bus.publish(agent.tenant_id, "dashboard", "agent.published", payload)
    bus.publish(agent.tenant_id, "insights", "agent.published", payload)
    return version


def agent_out(agent: Agent, version: AgentVersion | None) -> dict[str, Any]:
    return {
        "id": agent.id, "name": agent.name, "description": agent.description, "draft_config": agent.draft_config,
        "mode": (agent.draft_config or {}).get("mode", "inbound"),
        "published_version": {"id": version.id, "version": version.version, "created_at": version.created_at.isoformat()} if version else None,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }
