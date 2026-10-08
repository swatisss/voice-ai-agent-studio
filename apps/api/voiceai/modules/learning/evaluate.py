"""Evaluation runs: simulated callers replay cases against baseline and candidate configs; an LLM judge grades.

Spec: /architecture/evaluation.md, /prompts/caller-simulator.md, /prompts/eval-judge.md
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core import jobs, prompts
from voiceai.core.config import get_settings
from voiceai.core.db import sessionmaker, utcnow
from voiceai.core.errors import ApiError
from voiceai.core.events import bus
from voiceai.modules.learning.propose import candidate_config, cluster_evidence, proposal_summary
from voiceai.core.llm.gateway import gateway
from voiceai.core.tables import Agent, AgentVersion, Call, CallEvent, EvalResult, EvalRun, EvalScenario, FixProposal, Tenant
from voiceai.core.callerdirectory import caller_directory
from voiceai.modules.conversation.contract import call_transcript, open_simulation
from voiceai.modules.learning.domain import JudgeOut

log = logging.getLogger("voiceai.eval")
MAX_CALLER_TURNS = 8


def member_profile(member_ref: str | None, seed: str = "") -> dict[str, Any]:
    """The identity the simulated caller claims, from the configured caller directory."""
    profile = caller_directory().profile_for(member_ref, seed)
    if profile is None:
        return {}
    return {"name": profile.name, "member_id": profile.member_id,
            "date_of_birth": profile.date_of_birth, **profile.extra}


def profile_text(profile: dict[str, Any]) -> str:
    if not profile:
        return "not a member / no details"
    parts = [f"name {profile.get('name')}", f"member ID {profile.get('member_id')}", f"date of birth {profile.get('date_of_birth')}"]
    parts += [f"{k.replace('_', ' ')} {v}" for k, v in profile.items() if k not in ("name", "member_id", "date_of_birth")]
    return ", ".join(parts)


async def start_eval(s: AsyncSession, tenant_id: str, p: FixProposal) -> EvalRun:
    if p.status not in ("draft", "ready"):
        raise ApiError(409, "invalid_state", f"Proposal is {p.status}")
    agent = await s.get(Agent, p.agent_id)
    if not agent or not agent.published_version_id:
        raise ApiError(409, "agent_not_published", "Agent has no published version")
    run = EvalRun(tenant_id=tenant_id, agent_id=p.agent_id, proposal_id=p.id, baseline_version_id=agent.published_version_id)
    s.add(run)
    await s.flush()
    p.status, p.latest_eval_run_id = "evaluating", run.id
    await jobs.enqueue(s, tenant_id, "run_eval", {"proposal_id": p.id, "eval_run_id": run.id})
    await s.commit()
    bus.publish(tenant_id, "insights", "proposal.updated", proposal_summary(p))
    return run


async def simulate(
    tenant_id: str, agent_id: str, version_id: str, tenant_name: str, config: dict[str, Any],
    goal: str, profile: dict[str, Any],
) -> tuple[str, str]:
    """Runs one simulated call; returns (call_id, transcript-with-tools)."""
    session = await open_simulation(tenant_id=tenant_id, agent_id=agent_id, version_id=version_id,
                                    tenant_name=tenant_name, config=config)
    await session.start()
    lines: list[str] = [f"Agent: {session.history[-1]['content']}"]
    for _ in range(MAX_CALLER_TURNS):  # EV-04
        prompt = prompts.render("caller-simulator", caller_goal=goal, caller_profile=profile_text(profile), transcript="\n".join(lines))
        caller = (await gateway().chat("simulator", [{"role": "user", "content": prompt}])).text.strip()
        if not caller or "[HANGUP]" in caller.upper():
            break
        lines.append(f"Caller: {caller}")
        reply = await session.reply(caller)
        lines.append(f"Agent: {reply}")
        if session.state.ended or session.state.escalated:
            break
    await session.end("simulation_end")
    async with sessionmaker()() as s:
        return session.call_id, await call_transcript(s, tenant_id, session.call_id)


async def judge(goal: str, expected: str, transcript: str, policy: dict[str, Any]) -> JudgeOut:
    policy_text = "\n".join(
        [*(f"- Rule: {r}" for r in policy.get("rules", [])), *(f"- Never: {n}" for n in policy.get("never", [])),
         *(f"- Escalate when: {e}" for e in policy.get("escalate_when", []))]
    ) or "- (none)"
    prompt = prompts.render("eval-judge", caller_goal=goal, expected=expected, transcript=transcript, policy=policy_text)
    out, _ = await gateway().complete_json("judge", [{"role": "user", "content": prompt}], JudgeOut)
    return out


def passed(expected: str, j: JudgeOut) -> bool:
    if j.policy_violations:
        return False
    if expected == "escalated":  # EV-05
        return j.outcome == "escalated"
    return j.outcome == "resolved" and j.goal_met and j.grounded


@jobs.register("run_eval")
async def run_eval(tenant_id: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    started = time.perf_counter()
    async with sessionmaker()() as s:
        p = await s.get(FixProposal, payload["proposal_id"])
        run = await s.get(EvalRun, payload["eval_run_id"])
        if not p or not run:
            return
        version = await s.get(AgentVersion, run.baseline_version_id)
        tenant = await s.get(Tenant, tenant_id)
        base_cfg = version.config if version else {}
        cand_cfg = candidate_config(base_cfg, p)
        evidence = await cluster_evidence(s, p.cluster_id, limit=settings.ev_max_cluster_cases)
        scenarios = list((await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == p.agent_id, EvalScenario.tenant_id == tenant_id))).all())
    cases: list[dict[str, Any]] = []
    for i, e in enumerate(evidence):
        goal = e["caller_goal"] or e["gap_summary"]
        cases.append({"key": f"cluster-{i + 1}", "type": "cluster", "goal": goal, "expected": "resolved",
                      "profile": member_profile(e["caller_ref"], e["call_id"])})
    for sc in scenarios:
        cases.append({"key": sc.name, "type": "regression", "goal": sc.caller_goal, "expected": sc.expected, "profile": sc.caller_profile})
    work = [(c, "baseline") for c in cases if c["type"] == "cluster"] + [(c, "candidate") for c in cases]
    total, done = len(work), 0
    sem = asyncio.Semaphore(settings.ev_concurrency)
    lock = asyncio.Lock()
    tenant_name = tenant.name if tenant else tenant_id

    async def one(case: dict[str, Any], arm: str) -> None:
        nonlocal done
        cfg = base_cfg if arm == "baseline" else cand_cfg
        async with sem:
            try:
                call_id, transcript = await simulate(tenant_id, p.agent_id, run.baseline_version_id, tenant_name, cfg, case["goal"], case["profile"])
                verdict = await judge(case["goal"], case["expected"], transcript, cfg.get("policy", {}))
                ok, verdict_data = passed(case["expected"], verdict), verdict.model_dump()
            except Exception as exc:  # noqa: BLE001 - one failed case must not sink the run
                log.warning("eval case %s/%s failed: %s", case["key"], arm, exc)
                call_id, ok, verdict_data = None, False, {"error": str(exc)[:300]}
        async with sessionmaker()() as s2:
            s2.add(EvalResult(tenant_id=tenant_id, eval_run_id=run.id, case_key=case["key"], case_type=case["type"], arm=arm,
                              call_id=call_id, expected=case["expected"], passed=ok, judge=verdict_data))
            await s2.commit()
        async with lock:
            done += 1
            bus.publish(tenant_id, "insights", "eval.progress", {  # EV-06
                "proposal_id": p.id, "eval_run_id": run.id, "done": done, "total": total,
                "last": {"case_key": case["key"], "case_type": case["type"], "arm": arm, "passed": ok, "notes": verdict_data.get("notes", "")},
            })

    try:
        await asyncio.gather(*(one(c, a) for c, a in work))
        async with sessionmaker()() as s:
            results = list((await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == run.id))).all())
            cluster_n = sum(1 for c in cases if c["type"] == "cluster")
            base_pass = sum(1 for r in results if r.case_type == "cluster" and r.arm == "baseline" and r.passed)
            cand_pass = sum(1 for r in results if r.case_type == "cluster" and r.arm == "candidate" and r.passed)
            reg_n = sum(1 for c in cases if c["type"] == "regression")
            reg_pass = sum(1 for r in results if r.case_type == "regression" and r.passed)
            run_db = await s.get(EvalRun, run.id)
            p_db = await s.get(FixProposal, p.id)
            run_db.summary = {
                "cluster_cases": cluster_n, "baseline_pass": base_pass, "candidate_pass": cand_pass,
                "regression_cases": reg_n, "regression_pass": reg_pass,
                "lift_pct": round(100 * (cand_pass - base_pass) / cluster_n) if cluster_n else 0,
                "duration_s": round(time.perf_counter() - started, 1),
            }
            run_db.status, run_db.finished_at = "done", utcnow()
            p_db.status = "ready"
            await s.commit()
            bus.publish(tenant_id, "insights", "proposal.updated", proposal_summary(p_db))
    except Exception as exc:
        async with sessionmaker()() as s:
            run_db = await s.get(EvalRun, run.id)
            p_db = await s.get(FixProposal, p.id)
            run_db.status, run_db.error, run_db.finished_at = "failed", str(exc)[:1000], utcnow()
            p_db.status = "draft"
            await s.commit()
            bus.publish(tenant_id, "insights", "proposal.updated", proposal_summary(p_db))
        log.warning("eval run %s failed: %s", run.id, exc)  # recorded on the run; not retried
