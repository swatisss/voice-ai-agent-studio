"""Agents, versions, scenarios, tools and skills.

Spec: /api/rest-api.md (Agents; Tools, skills), /data/agent-config.md, /architecture/tenant-settings.md, /architecture/call-scoring.md,
/architecture/test-suites.md
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.agents import agent_out, default_config, publish, skill_dict, tool_dict, validate_config
from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.learning import scoring, test_suites
from voiceai.models import Agent, AgentVersion, CallScorecard, EvalResult, EvalRun, EvalScenario, Skill, Tool
from voiceai.schemas import ScenarioIn, SkillDef, ToolDef
from voiceai.tenancy import current_tenant
from voiceai.tenant_settings import ensure_pipeline_allowed

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
    await ensure_pipeline_allowed(s, tenant_id, cfg)  # MT-06
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
        cfg = validate_config(body.draft_config)
        await ensure_pipeline_allowed(s, tenant_id, cfg)  # MT-06
        agent.draft_config = cfg
    await s.commit()
    return agent_out(agent, await _version(s, agent))


@router.post("/agents/{agent_id}/publish")
async def publish_agent(agent_id: str, body: PublishBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = await _agent(s, tenant_id, agent_id)
    await ensure_pipeline_allowed(s, tenant_id, agent.draft_config or {})  # MT-06
    version = await publish(s, agent, body.change_note)
    await test_suites.start_on_publish(s, agent, version)  # TEST-08: the seeder publishes without this
    await s.commit()
    return {"id": version.id, "version": version.version, "created_at": version.created_at.isoformat()}


@router.get("/agents/{agent_id}/versions")
async def versions(agent_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await _agent(s, tenant_id, agent_id)
    rows = (await s.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()))).all()
    return {"items": [{"id": v.id, "version": v.version, "change_note": v.change_note, "source_proposal_id": v.source_proposal_id,
                       "created_at": v.created_at.isoformat()} for v in rows]}


@router.get("/agents/{agent_id}/checks")
async def checks(agent_id: str, source: Literal["draft", "published"] = "draft", tenant_id: str = Depends(current_tenant),
                 s: AsyncSession = Depends(get_session)) -> dict:
    """The checks call scoring would apply to the draft or the published version (API-09)."""
    agent = await _agent(s, tenant_id, agent_id)
    if source == "published":
        version = await _version(s, agent)
        if version is None:
            raise ApiError(409, "not_published", "The agent has no published version")
        config = version.config
    else:
        draft = agent.draft_config or {}
        skills = (await s.scalars(select(Skill).where(Skill.tenant_id == tenant_id, Skill.id.in_(draft.get("skill_ids") or [])))).all()
        config = {**draft, "skills": [skill_dict(k) for k in skills]}
    return {"items": [c.head() for c in scoring.catalogue(config)]}


@router.get("/agents/{agent_id}/scenarios")
async def scenarios(agent_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await _agent(s, tenant_id, agent_id)
    rows = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == agent_id).order_by(EvalScenario.created_at))).all()
    last = await s.scalar(select(EvalRun).where(EvalRun.agent_id == agent_id, EvalRun.kind == "suite", EvalRun.status == "done")
                          .order_by(EvalRun.created_at.desc()).limit(1))
    by = ((last.summary or {}).get("by_scenario") or {}) if last else {}
    return {"items": [{**test_suites.scenario_dict(r), "last": {"eval_run_id": last.id, **by[r.id]} if r.id in by else None} for r in rows]}


async def _scenario(s: AsyncSession, tenant_id: str, scenario_id: str) -> EvalScenario:
    row = await s.scalar(select(EvalScenario).where(EvalScenario.id == scenario_id, EvalScenario.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "scenario_not_found", "Scenario not found")
    return row


async def _save_scenario(s: AsyncSession, agent: Agent, row: EvalScenario, body: ScenarioIn) -> dict:
    await test_suites.check_tools(s, agent, body)  # TEST-10
    clash = await s.scalar(select(EvalScenario.id).where(EvalScenario.agent_id == agent.id, EvalScenario.name == body.name.strip(),
                                                         EvalScenario.id != (row.id or "")))
    if clash:
        raise ApiError(409, "name_taken", "Another scenario of this agent has that name")
    for k, v in test_suites.scenario_values(body).items():
        setattr(row, k, v)
    s.add(row)
    await s.commit()
    return test_suites.scenario_dict(row)


@router.post("/agents/{agent_id}/scenarios")
async def create_scenario(agent_id: str, body: ScenarioIn, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = await _agent(s, tenant_id, agent_id)
    return await _save_scenario(s, agent, EvalScenario(tenant_id=tenant_id, agent_id=agent_id), body)


@router.put("/scenarios/{scenario_id}")
async def update_scenario(scenario_id: str, body: dict[str, Any], tenant_id: str = Depends(current_tenant),
                          s: AsyncSession = Depends(get_session)) -> dict:
    row = await _scenario(s, tenant_id, scenario_id)
    agent = await _agent(s, tenant_id, row.agent_id)
    try:
        merged = ScenarioIn.model_validate({**test_suites.scenario_dict(row), **body})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", []))
        raise ApiError(422, "invalid_scenario", f"{where}: {first.get('msg')}") from exc
    return await _save_scenario(s, agent, row, merged)


@router.delete("/scenarios/{scenario_id}", status_code=204)
async def delete_scenario(scenario_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    row = await _scenario(s, tenant_id, scenario_id)
    await s.delete(row)
    await s.commit()
    return Response(status_code=204)


class TestRunBody(BaseModel):
    target: Literal["published", "draft", "version"] = "published"
    version_id: str | None = None
    repeats: int = Field(default=3, ge=1, le=5)
    scenario_ids: list[str] | None = None
    trigger: Literal["manual", "builder"] = "manual"


@router.post("/agents/{agent_id}/test-runs")
async def start_test_run(agent_id: str, body: TestRunBody, tenant_id: str = Depends(current_tenant),
                         s: AsyncSession = Depends(get_session)) -> dict:
    agent = await _agent(s, tenant_id, agent_id)
    run = await test_suites.start_run(s, agent, target=body.target, version_id=body.version_id, repeats=body.repeats,
                                      scenario_ids=body.scenario_ids, trigger=body.trigger)
    await s.commit()
    return {"eval_run_id": run.id}


@router.get("/agents/{agent_id}/test-runs")
async def list_test_runs(agent_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await _agent(s, tenant_id, agent_id)
    runs = (await s.scalars(select(EvalRun).where(EvalRun.agent_id == agent_id, EvalRun.kind == "suite")
                            .order_by(EvalRun.created_at.desc()).limit(50))).all()
    versions = dict((await s.execute(select(AgentVersion.id, AgentVersion.version).where(AgentVersion.agent_id == agent_id))).all())
    return {"items": [test_suites.run_out(r, versions.get(r.baseline_version_id)) for r in runs]}


@router.get("/test-runs/{run_id}")
async def get_test_run(run_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    run = await s.scalar(select(EvalRun).where(EvalRun.id == run_id, EvalRun.tenant_id == tenant_id, EvalRun.kind == "suite"))
    if run is None:
        raise ApiError(404, "run_not_found", "Test run not found")
    version = await s.get(AgentVersion, run.baseline_version_id) if run.baseline_version_id else None
    results = (await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == run.id).order_by(EvalResult.created_at))).all()
    call_ids = [r.call_id for r in results if r.call_id] or [""]
    cards = {c.call_id: c for c in (await s.scalars(select(CallScorecard).where(CallScorecard.call_id.in_(call_ids)))).all()}
    out = []
    for r in results:
        card = cards.get(r.call_id)
        out.append({"scenario_id": r.scenario_id, "scenario": r.scenario, "repeat": r.repeat, "passed": r.passed,
                    "failures": r.failures or [], "call_id": r.call_id,
                    "scorecard": {"score": card.score, "hard_fail": card.hard_fail,
                                  "failed_checks": [c["key"] for c in card.checks if c["verdict"] == "fail"]} if card else None})
    out.sort(key=lambda x: ((x["scenario"] or {}).get("name", ""), x["repeat"]))
    return {**test_suites.run_out(run, version.version if version else None), "results": out}


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
