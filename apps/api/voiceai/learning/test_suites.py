"""Test suites: per-agent scenarios run k times by a simulated caller against the published version, the draft or an
earlier version; each simulated call scored with the call scorer, expectations checked in code, pass^k reported.

Spec: /architecture/test-suites.md, /architecture/call-scoring.md, /architecture/evaluation.md (Simulation)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs
from voiceai.agents import build_snapshot
from voiceai.call_settings import pipeline_of
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.learning import scoring
from voiceai.learning.evaluate import simulate
from voiceai.models import Agent, AgentVersion, Call, CallEvent, EvalResult, EvalRun, EvalScenario, Escalation, Tenant, Tool
from voiceai.schemas import BUILTIN_TOOLS, ScenarioIn

log = logging.getLogger("voiceai.tests")
SCENARIO_FIELDS = ("name", "caller_goal", "caller_profile", "persona", "expected", "required_tools", "forbidden_tools",
                   "expected_results", "memory", "enabled")


def scenario_dict(sc: EvalScenario) -> dict[str, Any]:
    return {"id": sc.id, **{f: getattr(sc, f) for f in SCENARIO_FIELDS}}


async def check_tools(s: AsyncSession, agent: Agent, body: ScenarioIn) -> None:
    """TEST-10: tools named by a scenario must be the draft's tools or built-ins."""
    ids = (agent.draft_config or {}).get("tool_ids") or []
    names = set((await s.scalars(select(Tool.name).where(Tool.tenant_id == agent.tenant_id, Tool.id.in_(ids)))).all()) | BUILTIN_TOOLS
    unknown = sorted(body.tool_names() - names)
    if unknown:
        raise ApiError(422, "unknown_tool", f"Not a tool of this agent: {', '.join(unknown)}")


def scenario_values(body: ScenarioIn) -> dict[str, Any]:
    data = body.model_dump()
    data["name"] = data["name"].strip()
    return data


# ------------------------------------------------------------------ expectations
def _norm(v: Any) -> str:  # noqa: ANN401
    return str(v).strip().lower()


def _get(obj: Any, path: str) -> Any:  # noqa: ANN401
    for part in path.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def tool_runs(events: list[CallEvent]) -> list[tuple[str, dict[str, Any], bool, dict[str, Any]]]:
    """(name, args, ok, result) for each tool call, paired with its result by tool_call_id (or the next result of that name)."""
    results = [e for e in events if e.kind == "tool_result"]
    used: set[int] = set()
    out = []
    for e in events:
        if e.kind != "tool_call":
            continue
        data = e.data or {}
        match = next((r for r in results if r.seq > e.seq and r.seq not in used and (
            (data.get("tool_call_id") and (r.data or {}).get("tool_call_id") == data.get("tool_call_id"))
            or (not data.get("tool_call_id") and (r.data or {}).get("name") == data.get("name")))), None)
        if match is not None:
            used.add(match.seq)
        rdata = (match.data or {}) if match else {}
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        result = rdata.get("result") if isinstance(rdata.get("result"), dict) else {}
        out.append((str(data.get("name")), args, bool(rdata.get("ok")), result))
    return out


def outcome_of(escalated: bool, judge_outcome: str | None) -> str | None:
    return "escalated" if escalated or judge_outcome == "escalated" else judge_outcome


def check(scenario: dict[str, Any], events: list[CallEvent], outcome: str | None, card_checks: list[dict[str, Any]],
          hard_fail: bool) -> list[str]:
    """When one repeat passes (TEST-01, TEST-02): outcome, goal, no hard fail, tool expectations. Returns the failures."""
    failures: list[str] = []
    if outcome is None:
        failures.append("The judge could not decide the outcome")
    elif outcome != scenario["expected"]:
        failures.append(f"Expected {scenario['expected']}, got {outcome}")
    verdicts = {c["key"]: c for c in card_checks}
    if scenario["expected"] == "resolved" and (verdicts.get("outcome.goal_met") or {}).get("verdict") != "pass":
        failures.append("The caller's goal was not met")
    if hard_fail:
        failures += [f"Hard fail: {c['text']}" for c in card_checks if c["hard_gate"] and c["verdict"] == "fail"]
    runs = tool_runs(events)
    for req in scenario.get("required_tools") or []:
        ok_runs = [args for name, args, ok, _ in runs if name == req["name"] and ok]
        wanted = req.get("args") or {}
        if not any(all(_norm(args.get(k)) == _norm(v) for k, v in wanted.items()) for args in ok_runs):
            detail = ", ".join(f"{k}={v}" for k, v in wanted.items())
            failures.append(f"{req['name']} was never called{' with ' + detail if detail else ''}")
    for name in scenario.get("forbidden_tools") or []:
        if any(n == name and ok for n, _, ok, _ in runs):
            failures.append(f"{name} was called, but it is forbidden")
    for exp in scenario.get("expected_results") or []:
        values = [_get(result, exp["field"]) for n, _, ok, result in runs if n == exp["tool"] and ok]
        if not any(v is not None and _norm(v) == _norm(exp["equals"]) for v in values):
            failures.append(f"No {exp['tool']} result had {exp['field']} = {exp['equals']}")
    return failures


# ------------------------------------------------------------------ runs
async def resolve_target(s: AsyncSession, agent: Agent, target: str, version_id: str | None) -> tuple[dict[str, Any], str | None]:
    """The config to simulate and the version it is based on (/architecture/test-suites.md, Test run)."""
    if target == "draft":  # TEST-04: resolved like a publish, nothing created
        return await build_snapshot(s, agent.tenant_id, agent.draft_config or {}), agent.published_version_id
    if target == "version":
        version = await s.scalar(select(AgentVersion).where(AgentVersion.id == (version_id or ""), AgentVersion.agent_id == agent.id))
        if version is None:
            raise ApiError(404, "version_not_found", "Version not found for this agent")
        return version.config, version.id
    if not agent.published_version_id:
        raise ApiError(409, "not_published", "The agent has no published version")
    version = await s.get(AgentVersion, agent.published_version_id)
    return version.config, version.id


async def start_run(s: AsyncSession, agent: Agent, *, target: str = "published", version_id: str | None = None,
                    repeats: int = 3, scenario_ids: list[str] | None = None, trigger: str = "manual") -> EvalRun:
    """TEST-05: one running suite per agent, enabled scenarios only. Caller commits."""
    running = await s.scalar(select(EvalRun.id).where(EvalRun.agent_id == agent.id, EvalRun.kind == "suite", EvalRun.status == "running"))
    if running:
        raise ApiError(409, "run_in_progress", "A test run is already running for this agent")
    config, base = await resolve_target(s, agent, target, version_id)
    q = select(EvalScenario).where(EvalScenario.agent_id == agent.id, EvalScenario.tenant_id == agent.tenant_id,
                                   EvalScenario.enabled.is_(True))
    if scenario_ids:
        q = q.where(EvalScenario.id.in_(scenario_ids))
    scenarios = list((await s.scalars(q.order_by(EvalScenario.created_at))).all())
    if not scenarios:
        raise ApiError(422, "no_scenarios", "This agent has no enabled test scenarios")
    run = EvalRun(tenant_id=agent.tenant_id, agent_id=agent.id, kind="suite", baseline_version_id=base, target=target,
                  config=config, repeats=repeats, trigger=trigger, scenario_ids=[sc.id for sc in scenarios])
    s.add(run)
    await s.flush()
    await jobs.enqueue(s, agent.tenant_id, "run_test_suite", {"eval_run_id": run.id})
    return run


async def start_on_publish(s: AsyncSession, agent: Agent, version: AgentVersion) -> EvalRun | None:
    """TEST-08: a new version gets a baseline run when the agent asks for it; nothing is raised if it cannot start."""
    if not scoring.evaluation_settings(version.config).test_on_publish:
        return None
    try:
        return await start_run(s, agent, target="version", version_id=version.id, trigger="publish")
    except ApiError as exc:
        log.info("no test run on publish of %s: %s", agent.id, exc.detail)
        return None


def summarize(results: list[EvalResult], cards: dict[str, Any], repeats: int, config: dict[str, Any], duration: float) -> dict[str, Any]:
    by: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by[r.scenario_id or r.case_key].append(r.passed)
    rates: dict[str, list[str]] = defaultdict(list)
    texts: dict[str, str] = {}
    for card in cards.values():
        for c in card.checks:
            rates[c["key"]].append(c["verdict"])
            texts[c["key"]] = c["text"]
    check_pass_rates = {}
    for key, vs in sorted(rates.items()):
        decided = vs.count("pass") + vs.count("fail")
        check_pass_rates[key] = round(vs.count("pass") / decided, 4) if decided else None
    pipeline = pipeline_of(config)
    return {
        "scenarios": len(by), "repeats": repeats,
        "pass_all": sum(1 for v in by.values() if v and all(v)), "pass_any": sum(1 for v in by.values() if any(v)),
        "pass_rate": round(sum(r.passed for r in results) / len(results), 4) if results else None,
        "hard_fails": sum(1 for card in cards.values() if card.hard_fail),
        "check_pass_rates": check_pass_rates, "check_texts": texts,
        "by_scenario": {k: {"passed": sum(v), "of": len(v)} for k, v in by.items()},
        "duration_s": round(duration, 1), "pipeline": pipeline,
        "fidelity": "text_approximation" if pipeline == "realtime" else "faithful",
    }


@jobs.register("run_test_suite")
async def run_test_suite(tenant_id: str, payload: dict[str, Any]) -> None:
    started = time.perf_counter()
    async with sessionmaker()() as s:
        run = await s.scalar(select(EvalRun).where(EvalRun.id == payload["eval_run_id"], EvalRun.tenant_id == tenant_id))
        if run is None or run.status != "running":
            return
        agent = await s.get(Agent, run.agent_id)
        tenant = await s.get(Tenant, tenant_id)
        scenarios = list((await s.scalars(select(EvalScenario).where(EvalScenario.id.in_(run.scenario_ids or [])))).all())
        version_id = run.baseline_version_id or (agent.published_version_id if agent else None) or ""
    config = run.config or {}
    tenant_name = tenant.name if tenant else tenant_id
    work = [(scenario_dict(sc), k) for sc in scenarios for k in range(1, run.repeats + 1)]
    total, done = len(work), 0
    sem = asyncio.Semaphore(get_settings().ev_concurrency)
    lock = asyncio.Lock()
    cards: dict[str, Any] = {}

    async def one(sc: dict[str, Any], repeat: int) -> None:
        nonlocal done
        call_id, ok, failures = None, False, []
        async with sem:
            try:
                call_id, _ = await simulate(tenant_id, run.agent_id, version_id, tenant_name, config, sc["caller_goal"],
                                            sc["caller_profile"] or {}, persona=sc["persona"], memory=sc["memory"])
                async with sessionmaker()() as s2:
                    call = await s2.get(Call, call_id)
                    card = await scoring.score(s2, call, config=config, always_judge=True, goal=sc["caller_goal"], expected=sc["expected"])
                    events = list((await s2.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())
                    escalated = await s2.scalar(select(Escalation.id).where(Escalation.call_id == call_id)) is not None
                    failures = check(sc, events, outcome_of(escalated, getattr(card, "judge_outcome", None)), card.checks, card.hard_fail)
                    cards[call_id] = card
                    await s2.commit()
                ok = not failures
            except Exception as exc:  # noqa: BLE001 - one failed repeat must not sink the run
                log.warning("test %s/%s failed: %s", sc["name"], repeat, exc)
                failures = [f"The simulation failed: {str(exc)[:200]}"]
        async with sessionmaker()() as s3:
            s3.add(EvalResult(tenant_id=tenant_id, eval_run_id=run.id, case_key=sc["name"], case_type="suite", arm="target",
                              scenario_id=sc["id"], repeat=repeat, scenario=sc, call_id=call_id, expected=sc["expected"],
                              passed=ok, failures=failures, judge={}))
            await s3.commit()
        async with lock:
            done += 1
            bus.publish(tenant_id, "evaluation", "test_run.progress", {  # TEST-09
                "eval_run_id": run.id, "agent_id": run.agent_id, "done": done, "total": total,
                "last": {"scenario_id": sc["id"], "repeat": repeat, "passed": ok}})

    try:
        await asyncio.gather(*(one(sc, k) for sc, k in work))
        async with sessionmaker()() as s:
            results = list((await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == run.id))).all())
            run_db = await s.get(EvalRun, run.id)
            run_db.summary = summarize(results, cards, run.repeats, config, time.perf_counter() - started)
            run_db.status, run_db.finished_at = "done", utcnow()
            await s.commit()
            bus.publish(tenant_id, "evaluation", "test_run.finished",
                        {"eval_run_id": run.id, "agent_id": run.agent_id, "status": "done", "summary": run_db.summary})
    except Exception as exc:
        async with sessionmaker()() as s:
            run_db = await s.get(EvalRun, run.id)
            run_db.status, run_db.error, run_db.finished_at = "failed", str(exc)[:1000], utcnow()
            await s.commit()
        bus.publish(tenant_id, "evaluation", "test_run.finished", {"eval_run_id": run.id, "agent_id": run.agent_id, "status": "failed", "summary": {}})


def run_out(run: EvalRun, version: int | None) -> dict[str, Any]:
    return {"id": run.id, "target": run.target, "version": version, "version_id": run.baseline_version_id, "trigger": run.trigger,
            "status": run.status, "repeats": run.repeats, "summary": run.summary or {}, "error": run.error,
            "created_at": run.created_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None}
