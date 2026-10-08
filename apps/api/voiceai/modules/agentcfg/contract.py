"""What other modules may use from agent configuration. Nothing else here is theirs.

Spec: /data/agent-config.md, /architecture/modular-structure.md, /architecture/personas.md

Everything a module outside `agentcfg` needs goes through this file, so extracting agent
configuration later means replacing these functions with a client and changing nothing else. In
particular `apply_fix_and_publish` exists because fleet learning used to write four of this
module's tables directly: it now states *what* the fix is and lets this module decide how to
store it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_owned
from voiceai.core.tables import Agent, AgentVersion, Persona
from voiceai.modules.agentcfg.domain import VAD_STOP_MS, SkillDef, ToolDef, TurnDetectionPatch, TurnSettings
from voiceai.modules.agentcfg.settings import effective_settings, effective_turn, persona_dict, settings_view

__all__ = [
    "VAD_STOP_MS", "FixSpec", "SkillDef", "ToolDef", "TurnDetectionPatch", "TurnSettings", "VersionRef",
    "apply_fix_and_publish", "effective_settings",
    "effective_turn", "get_persona", "persona_dict", "published_config", "publish_draft", "settings_view",
]


@dataclass(frozen=True)
class VersionRef:
    id: str
    version: int


@dataclass(frozen=True)
class FixSpec:
    """A change to an agent, described by whoever proposed it rather than applied by them.

    `tools` and `skills` are definition payloads as /data/agent-config.md specifies them; a tool
    matching an existing one by name within the tenant is reused rather than duplicated.
    """

    knowledge_doc_ids: tuple[str, ...] = ()
    tools: tuple[dict[str, Any], ...] = ()
    skills: tuple[dict[str, Any], ...] = ()
    policy_rules: tuple[str, ...] = ()


async def get_persona(s: AsyncSession, tenant_id: str, persona_id: str) -> Persona | None:
    """A tenant's persona, or None when it is not theirs (MT-05)."""
    return await get_owned(s, Persona, tenant_id, persona_id)


async def published_config(s: AsyncSession, tenant_id: str, agent_id: str) -> dict[str, Any]:
    """The snapshot a call would run against, or {} when the agent has no published version."""
    agent = await get_owned(s, Agent, tenant_id, agent_id)
    if agent is None or not agent.published_version_id:
        return {}
    version = await s.get(AgentVersion, agent.published_version_id)
    return version.config if version else {}


async def publish_draft(s: AsyncSession, tenant_id: str, agent_id: str, change_note: str = "") -> VersionRef:
    """Publish the agent's current draft as a new version."""
    from voiceai.modules.agentcfg.service import publish

    agent = await get_owned(s, Agent, tenant_id, agent_id)
    if agent is None:
        raise LookupError(f"no agent {agent_id} for tenant {tenant_id}")
    version = await publish(s, agent, change_note)
    return VersionRef(id=version.id, version=version.version)


async def apply_fix_and_publish(
    s: AsyncSession, tenant_id: str, agent_id: str, fix: FixSpec, change_note: str,
    source_proposal_id: str | None = None,
) -> VersionRef:
    """Fold `fix` into the agent's draft and publish it. The caller commits."""
    from voiceai.modules.agentcfg.service import apply_fix, publish

    agent = await get_owned(s, Agent, tenant_id, agent_id)
    if agent is None:
        raise LookupError(f"no agent {agent_id} for tenant {tenant_id}")
    await apply_fix(s, agent, fix)
    version = await publish(s, agent, change_note=change_note, source_proposal_id=source_proposal_id)
    return VersionRef(id=version.id, version=version.version)
