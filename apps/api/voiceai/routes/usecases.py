"""Use cases (editable, CP-0024), outbound target lists, the agents' routing profiles and the routing suite.

Spec: /api/rest-api.md (Use cases and outbound, Evaluation), /product/use-cases.md, /architecture/call-modes.md,
/architecture/capability-catalog.md
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.models import Agent, AgentVersion, CapabilityProfile, EvalRun, RoutingCase, UseCase
from voiceai.routing import catalog, suite
from voiceai.runtime import outbound
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api")

CHANNELS = ("voice", "chat", "phone")


def _utterances(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    cleaned = [" ".join(u.split()) for u in v]
    if not 1 <= len(cleaned) <= 20 or any(not 3 <= len(u) <= 200 for u in cleaned):
        raise ValueError("give 1-20 sample utterances of 3-200 characters each")
    return cleaned


class UseCaseBody(BaseModel):
    agent_id: str
    title: str = Field(min_length=3, max_length=120)
    summary: str = Field(default="", max_length=600)
    category: str = Field(default="", max_length=120)
    channels: list[Literal["voice", "chat", "phone"]] = Field(default_factory=lambda: ["voice", "chat"])
    sample_utterances: list[str]
    demo_callers: list[dict] = Field(default_factory=list)
    sort: int | None = None

    @field_validator("sample_utterances")
    @classmethod
    def _samples(cls, v: list[str] | None) -> list[str] | None:
        return _utterances(v)


class UseCasePatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    summary: str | None = Field(default=None, max_length=600)
    category: str | None = Field(default=None, max_length=120)
    channels: list[Literal["voice", "chat", "phone"]] | None = None
    sample_utterances: list[str] | None = None
    demo_callers: list[dict] | None = None
    sort: int | None = None

    @field_validator("sample_utterances")
    @classmethod
    def _samples(cls, v: list[str] | None) -> list[str] | None:
        return _utterances(v)


def use_case_out(u: UseCase, agent: Agent | None) -> dict:
    return {
        "id": u.id, "category": u.category, "title": u.title, "summary": u.summary, "channels": list(u.channels or []),
        "mode": (agent.draft_config or {}).get("mode", "inbound") if agent else "inbound",
        "agent_id": u.agent_id, "agent_name": agent.name if agent else None,
        "published": bool(agent and agent.published_version_id),
        "sample_utterances": list(u.sample_utterances or []), "demo_callers": list(u.demo_callers or []), "sort": u.sort,
        "updated_at": (u.updated_at or u.created_at).isoformat() if (u.updated_at or u.created_at) else None,
    }


async def _agent(s: AsyncSession, tenant_id: str, agent_id: str) -> Agent:
    agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    if agent is None:  # CAT-05: another tenant's agent
        raise ApiError(404, "agent_not_found", "Agent not found")
    return agent


async def _use_case(s: AsyncSession, tenant_id: str, use_case_id: str) -> UseCase:
    row = await s.scalar(select(UseCase).where(UseCase.id == use_case_id, UseCase.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "use_case_not_found", "Use case not found")
    return row


async def _title_free(s: AsyncSession, tenant_id: str, agent_id: str, title: str, exclude: str | None = None) -> None:
    q = select(UseCase.id).where(UseCase.tenant_id == tenant_id, UseCase.agent_id == agent_id, func.lower(UseCase.title) == title.lower())
    if exclude:
        q = q.where(UseCase.id != exclude)
    if await s.scalar(q):
        raise ApiError(409, "title_taken", f"This agent already has a use case called '{title}'")


async def _reindex(s: AsyncSession, agent: Agent) -> None:
    if agent.published_version_id:  # API-11
        await catalog.enqueue_index(s, agent.tenant_id, agent.id)


@router.get("/use-cases")
async def use_cases(agent_id: str | None = None, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    q = select(UseCase).where(UseCase.tenant_id == tenant_id).order_by(UseCase.sort, UseCase.created_at)
    if agent_id:
        q = q.where(UseCase.agent_id == agent_id)
    rows = (await s.scalars(q)).all()
    agents = {a.id: a for a in (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id))).all()}
    return {"items": [use_case_out(u, agents.get(u.agent_id)) for u in rows]}


@router.post("/use-cases", status_code=201)
async def create_use_case(body: UseCaseBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = await _agent(s, tenant_id, body.agent_id)
    title = body.title.strip()
    await _title_free(s, tenant_id, agent.id, title)
    sort = body.sort if body.sort is not None else (await s.scalar(select(func.max(UseCase.sort)).where(UseCase.tenant_id == tenant_id)) or 0) + 1
    row = UseCase(tenant_id=tenant_id, agent_id=agent.id, title=title, summary=body.summary.strip(), category=body.category.strip(),
                  channels=list(body.channels), sample_utterances=body.sample_utterances, demo_callers=body.demo_callers, sort=sort)
    s.add(row)
    await s.flush()
    await _reindex(s, agent)
    await s.commit()
    return use_case_out(row, agent)


@router.put("/use-cases/{use_case_id}")
async def update_use_case(use_case_id: str, body: UseCasePatch, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row = await _use_case(s, tenant_id, use_case_id)
    agent = await _agent(s, tenant_id, row.agent_id)
    if body.title is not None:
        await _title_free(s, tenant_id, agent.id, body.title.strip(), exclude=row.id)
        row.title = body.title.strip()
    for field in ("summary", "category"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value.strip())
    for field in ("channels", "sample_utterances", "demo_callers", "sort"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, list(value) if isinstance(value, list) else value)
    await _reindex(s, agent)
    await s.commit()
    return use_case_out(row, agent)


@router.delete("/use-cases/{use_case_id}", status_code=204)
async def delete_use_case(use_case_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    row = await _use_case(s, tenant_id, use_case_id)
    agent = await _agent(s, tenant_id, row.agent_id)
    await s.delete(row)
    await _reindex(s, agent)
    await s.commit()
    return Response(status_code=204)


@router.get("/agents/{agent_id}/capability")
async def capability(agent_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await _agent(s, tenant_id, agent_id)
    p = await s.scalar(select(CapabilityProfile).where(CapabilityProfile.agent_id == agent_id, CapabilityProfile.tenant_id == tenant_id))
    if p is None:
        raise ApiError(404, "not_routable", "This agent has no routing profile (not published, outbound, or routing switched off)")
    card = p.card or {}
    return {"status": p.status, "built_at": p.built_at.isoformat(), "error": p.error, "summary": p.summary, "skills": card.get("skills", []),
            "tools": card.get("tools", []), "knowledge": card.get("knowledge", []), "generated_examples": card.get("generated_examples", [])}


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
    targets = await outbound.fetch_targets((config.get("outbound") or {}).get("targets_url", ""), request.app)
    return {"items": [
        {"member_ref": t["member_ref"], "first_name": t.get("first_name", ""), "summary": t.get("summary", ""), "context": t.get("context") or {}}
        for t in targets
    ]}


# ---------------------------------------------------------------- routing suite
class CaseBody(BaseModel):
    utterance: str = Field(min_length=3, max_length=300)
    expected_agent_id: str  # an agent id, or "?" for a vague request whose right result is to ask (CAT-09)
    scope: Literal["member", "staff"] = "member"  # used for "?" cases; otherwise the agent's scope
    enabled: bool = True


class CasePatch(BaseModel):
    utterance: str | None = Field(default=None, min_length=3, max_length=300)
    expected_agent_id: str | None = None
    enabled: bool | None = None


async def _routable_scope(s: AsyncSession, tenant_id: str, agent_id: str) -> str:
    agent = await _agent(s, tenant_id, agent_id)
    version = await s.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None
    if version is None or not catalog.routable(version.config):
        raise ApiError(422, "not_routable", "Choose a published agent that callers can be routed to")
    return catalog.scope_of(version.config) or "member"


def case_out(c: RoutingCase, names: dict[str, str]) -> dict:
    return {"id": c.id, "utterance": c.utterance, "expected_agent_id": c.expected_agent_id, "expected_agent_name": names.get(c.expected_agent_id),
            "scope": c.scope, "source": c.source, "enabled": c.enabled}


async def _names(s: AsyncSession, tenant_id: str) -> dict[str, str]:
    return {a.id: a.name for a in (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id))).all()}


@router.get("/routing/cases")
async def routing_cases(scope: str | None = None, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    q = select(RoutingCase).where(RoutingCase.tenant_id == tenant_id).order_by(RoutingCase.source, RoutingCase.created_at)
    if scope:
        q = q.where(RoutingCase.scope == scope)
    names = await _names(s, tenant_id)
    return {"items": [case_out(c, names) for c in (await s.scalars(q)).all()]}


@router.post("/routing/cases", status_code=201)
async def create_case(body: CaseBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    scope = body.scope if body.expected_agent_id == suite.VAGUE else await _routable_scope(s, tenant_id, body.expected_agent_id)
    if (await s.scalar(select(func.count()).select_from(RoutingCase).where(RoutingCase.tenant_id == tenant_id, RoutingCase.source == "manual")) or 0) >= suite.MAX_CASES:
        raise ApiError(409, "too_many_cases", f"At most {suite.MAX_CASES} manual cases")
    row = RoutingCase(tenant_id=tenant_id, utterance=" ".join(body.utterance.split()), expected_agent_id=body.expected_agent_id, scope=scope,
                      source="manual", enabled=body.enabled)
    s.add(row)
    await s.commit()
    return case_out(row, await _names(s, tenant_id))


@router.put("/routing/cases/{case_id}")
async def update_case(case_id: str, body: CasePatch, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row = await s.scalar(select(RoutingCase).where(RoutingCase.id == case_id, RoutingCase.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "case_not_found", "Routing case not found")
    if body.expected_agent_id is not None and body.expected_agent_id != suite.VAGUE:
        row.scope = await _routable_scope(s, tenant_id, body.expected_agent_id)
        row.expected_agent_id = body.expected_agent_id
    if body.utterance is not None:
        row.utterance = " ".join(body.utterance.split())
    if body.enabled is not None:
        row.enabled = body.enabled
    await s.commit()
    return case_out(row, await _names(s, tenant_id))


@router.delete("/routing/cases/{case_id}", status_code=204)
async def delete_case(case_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    row = await s.scalar(select(RoutingCase).where(RoutingCase.id == case_id, RoutingCase.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "case_not_found", "Routing case not found")
    await s.delete(row)
    await s.commit()
    return Response(status_code=204)


class RunBody(BaseModel):
    compare: bool = False


@router.post("/routing/runs", status_code=201)
async def start_routing_run(body: RunBody | None = None, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    run = await suite.start_manual(s, tenant_id, compare=bool(body and body.compare))  # CAT-09
    await s.commit()
    return {"eval_run_id": run.id}


@router.get("/routing/runs")
async def routing_runs(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(EvalRun).where(EvalRun.tenant_id == tenant_id, EvalRun.kind == "routing")
                            .order_by(EvalRun.created_at.desc()).limit(50))).all()
    return {"items": [await suite.run_out(s, r) for r in rows]}


@router.get("/routing/summary")
async def routing_summary(days: int = 28, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    """XFR-08: decisions, methods, fallbacks, clarifications, misroutes and transfers for the Routing view."""
    from voiceai.routing import learning as routing_learning

    if days not in (7, 28, 90):
        raise ApiError(422, "invalid_days", "days must be 7, 28 or 90")
    return await routing_learning.summary(s, tenant_id, days)


@router.get("/routing/runs/{run_id}")
async def routing_run(run_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row = await s.scalar(select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant_id == tenant_id, EvalRun.kind == "routing"))
    if row is None:
        raise ApiError(404, "run_not_found", "Routing run not found")
    return await suite.run_out(s, row, with_results=True)
