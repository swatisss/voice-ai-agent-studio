"""Front-desk settings of routed conversations: persona, pipeline, default agents, threshold, clarifications.

Spec: /architecture/supervisor-routing.md (Front desk settings), /architecture/tenant-settings.md (Front desk)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.call_settings import persona_dict
from voiceai.errors import ApiError
from voiceai.models import Agent, AgentVersion, Persona, TenantSettings

CONNECTING_DEFAULT = "One moment while I connect you."
GREETING_DEFAULT = "Thanks for calling. How can I help you today?"
DISCLOSURE_DEFAULT = "I'm a virtual assistant, and this call may be recorded for quality."


@dataclass
class FrontDesk:
    persona_id: str | None = None
    pipeline: str = "cascade"
    default_agents: dict[str, str | None] = field(default_factory=lambda: {"member": None, "staff": None})
    min_confidence: float | None = None
    max_clarifications: int = 1
    connecting_message: str = CONNECTING_DEFAULT
    min_routing_accuracy: float = 0.9
    routing_mode: str = "embedding"  # embedding | decision_model (CP-0028)
    clear_win: float = 0.80
    clear_margin: float = 0.10

    def view(self) -> dict[str, Any]:
        return asdict(self)


class FrontDeskPatch(BaseModel):
    persona_id: str | None = None
    pipeline: Literal["cascade", "realtime"] | None = None
    default_agents: dict[Literal["member", "staff"], str | None] | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    max_clarifications: int | None = Field(default=None, ge=0, le=2)
    connecting_message: str | None = Field(default=None, min_length=1, max_length=120)
    min_routing_accuracy: float | None = Field(default=None, ge=0.5, le=1)
    routing_mode: Literal["embedding", "decision_model"] | None = None
    clear_win: float | None = Field(default=None, ge=0.5, le=0.99)
    clear_margin: float | None = Field(default=None, ge=0, le=0.5)

    model_config = {"extra": "forbid"}


async def _first_persona(s: AsyncSession, tenant_id: str) -> Persona | None:
    return await s.scalar(select(Persona).where(Persona.tenant_id == tenant_id).order_by(Persona.name))


async def load(s: AsyncSession, tenant_id: str) -> FrontDesk:
    """The stored front desk with defaults filled in (API-13); the persona defaults to the first by name."""
    row = await s.get(TenantSettings, tenant_id)
    raw = dict((row.front_desk if row else None) or {})
    fd = FrontDesk(**{k: v for k, v in raw.items() if k in FrontDesk.__dataclass_fields__})
    fd.default_agents = {"member": None, "staff": None, **(fd.default_agents or {})}
    if not fd.persona_id or (await s.get(Persona, fd.persona_id)) is None:
        first = await _first_persona(s, tenant_id)
        fd.persona_id = first.id if first else None
    return fd


async def persona(s: AsyncSession, tenant_id: str, fd: FrontDesk) -> dict[str, Any]:
    row = await s.get(Persona, fd.persona_id) if fd.persona_id else None
    if row is None or row.tenant_id != tenant_id:
        return {"id": None, "name": "Front desk", "voice": "aura-2-thalia-en", "speed": 1.0, "greeting": GREETING_DEFAULT,
                "disclosure": DISCLOSURE_DEFAULT, "opening": "", "style": ""}
    return persona_dict(row)


async def _routable_in(s: AsyncSession, tenant_id: str, agent_id: str, scope: str) -> bool:
    from voiceai.routing import catalog

    agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    version = await s.get(AgentVersion, agent.published_version_id) if agent and agent.published_version_id else None
    return bool(version and catalog.routable(version.config) and catalog.scope_of(version.config) == scope)


async def update(s: AsyncSession, tenant_id: str, patch: FrontDeskPatch) -> FrontDesk:
    from voiceai import tenant_settings as ts

    fd = await load(s, tenant_id)
    if patch.persona_id is not None:
        row = await s.get(Persona, patch.persona_id)
        if row is None or row.tenant_id != tenant_id:
            raise ApiError(422, "invalid_settings", "Unknown persona")
        fd.persona_id = patch.persona_id
    if patch.pipeline is not None:
        if patch.pipeline not in await ts.allowed_pipelines(s, tenant_id):
            raise ApiError(422, "pipeline_not_allowed", "This voice pipeline is not enabled for this business unit")
        fd.pipeline = patch.pipeline
    if patch.default_agents is not None:
        for scope, agent_id in patch.default_agents.items():
            if agent_id and not await _routable_in(s, tenant_id, agent_id, scope):
                raise ApiError(422, "invalid_settings", f"The default agent for {scope} must be a routable {'inbound' if scope == 'member' else 'internal'} agent")
            fd.default_agents[scope] = agent_id or None
    for name in ("min_confidence", "max_clarifications", "connecting_message", "min_routing_accuracy", "routing_mode", "clear_win", "clear_margin"):
        value = getattr(patch, name)
        if value is not None:
            setattr(fd, name, value.strip() if isinstance(value, str) else value)
    row = await s.get(TenantSettings, tenant_id)
    if row is None:
        row = TenantSettings(tenant_id=tenant_id, allowed_pipelines=["cascade"], openai_platform_fallback=True)
        s.add(row)
    row.front_desk = fd.view()
    return fd


async def default_agent(s: AsyncSession, tenant_id: str, fd: FrontDesk, scope: str) -> str | None:
    """The scope's default, if it is still routable (MT-16: an unpublished default counts as none)."""
    agent_id = fd.default_agents.get(scope)
    if agent_id and await _routable_in(s, tenant_id, agent_id, scope):
        return agent_id
    return None
