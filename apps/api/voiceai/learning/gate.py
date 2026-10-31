"""Proposal evaluation and its gate: cluster, held-out, derived and test-suite cases on both arms, every simulated call
scored, and the four gate rules.

Spec: /architecture/evaluation.md, /architecture/self-learning.md (Gate), /architecture/test-suites.md (When one repeat passes)
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from voiceai import jobs
from voiceai.call_settings import pipeline_of
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.events import bus
from voiceai.learning import scoring, test_suites
from voiceai.learning.evaluate import member_profile, simulate
from voiceai.learning.propose import candidate_config, cluster_evidence, proposal_summary
from voiceai.models import AgentVersion, Call, CallEvent, Escalation, EvalResult, EvalRun, EvalScenario, FixProposal, Tenant
from voiceai.schemas import LearningConfig

log = logging.getLogger("voiceai.eval")
HELD_OUT = 4
SLOWDOWN = 1.2
SLOWDOWN_GRACE_MS = 200  # differences this small are noise, not a slowdown


def _case(key: str, kind: str, scenario: dict[str, Any], repeats: int = 1, scenario_id: str | None = None) -> dict[str, Any]:
    base = {"expected": "resolved", "caller_profile": {}, "persona": "calm", "memory": [], "required_tools": [],
            "forbidden_tools": [], "expected_results": []}
    return {"key": key, "type": kind, "scenario": {**base, **scenario}, "repeats": repeats, "scenario_id": scenario_id}


def evaluate_gate(results: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    """The gate of /architecture/self-learning.md from per-(case, arm, repeat) results:
    {key, type, arm, repeat, passed, hard_fail, latencies, name}."""
    def passes(kind: str, arm: str) -> int:
        return sum(1 for r in results if r["type"] == kind and r["arm"] == arm and r["passed"])

    reasons: list[str] = []
    cluster_n = len({r["key"] for r in results if r["type"] == "cluster"})
    held_n = len({r["key"] for r in results if r["type"] == "held_out"})
    base_lift = passes("cluster", "baseline") + passes("held_out", "baseline")
    cand_lift = passes("cluster", "candidate") + passes("held_out", "candidate")
    if cand_lift < base_lift + 1:
        reasons.append(f"No lift: {cand_lift} passing cluster and held-out cases against {base_lift} on the current version")
    if held_n and passes("held_out", "candidate") < math.ceil(held_n / 2):
        reasons.append(f"Held-out cases: {passes('held_out', 'candidate')} of {held_n} pass (needs at least half)")
    regression: dict[str, dict[str, Any]] = {}
    for r in results:
        if r["type"] == "regression":
            entry = regression.setdefault(r["key"], {"name": r["name"], "baseline": 0, "candidate": 0})
            entry[r["arm"]] += r["passed"]
    regressed = [v for v in regression.values() if v["baseline"] == repeats and v["candidate"] < repeats - 1]
    if regressed:  # SL-10
        names = ", ".join(f"{v['name']} {v['baseline']}/{repeats} → {v['candidate']}/{repeats}" for v in regressed)
        reasons.append(f"{len(regressed)} test scenario{'s' if len(regressed) > 1 else ''} regressed: {names}")
    hard = {(r["key"], r["repeat"]): r["hard_fail"] for r in results if r["arm"] == "baseline"}
    new_hard = [r for r in results if r["arm"] == "candidate" and r["hard_fail"] and not hard.get((r["key"], r["repeat"]), False)]
    if new_hard:
        reasons.append(f"New hard fails on {len(new_hard)} case{'s' if len(new_hard) > 1 else ''}: " + ", ".join(sorted({r['name'] for r in new_hard})))
    p95 = {arm: scoring.nearest_rank([x for r in results if r["arm"] == arm for x in r["latencies"]], 0.95) for arm in ("baseline", "candidate")}
    slower = bool(p95["baseline"] and p95["candidate"] and p95["candidate"] > SLOWDOWN * p95["baseline"]
                  and p95["candidate"] - p95["baseline"] > SLOWDOWN_GRACE_MS)
    if slower:
        reasons.append(f"Slower: p95 {p95['candidate']} ms against {p95['baseline']} ms")
    return {
        "cluster_cases": cluster_n, "baseline_pass": passes("cluster", "baseline"), "candidate_pass": passes("cluster", "candidate"),
        "held_out_cases": held_n, "held_out_baseline_pass": passes("held_out", "baseline"), "held_out_candidate_pass": passes("held_out", "candidate"),
        "regression_cases": len(regression), "regression_repeats": repeats, "regression": regression,
        "regression_pass": len(regression) - len(regressed),
        "hard_fails": {arm: sum(1 for r in results if r["arm"] == arm and r["hard_fail"]) for arm in ("baseline", "candidate")},
        "p95_ms": p95,
        "lift_pct": round(100 * (passes("cluster", "candidate") - passes("cluster", "baseline")) / cluster_n) if cluster_n else 0,
        "gate": {"passed": not reasons, "reasons": reasons},
    }


async def gather_cases(s, p: FixProposal, base_cfg: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: ANN001
    """Cluster cases (the drafting evidence), held-out members, derived scenarios and the enabled test suite (SL-08)."""
    settings = get_settings()
    members = await cluster_evidence(s, p.cluster_id, limit=60)
    shown = set(p.payload.get("evidence_call_ids") or [m["call_id"] for m in members[:10]])
    cases = []
    for i, e in enumerate([m for m in members if m["call_id"] in shown][: settings.ev_max_cluster_cases]):
        cases.append(_case(f"cluster-{i + 1}", "cluster", {"caller_goal": e["caller_goal"] or e["gap_summary"],
                                                           "caller_profile": member_profile(e["caller_ref"], e["call_id"])}))
    for i, e in enumerate([m for m in members if m["call_id"] not in shown and (m["caller_goal"] or m["gap_summary"])][:HELD_OUT]):
        cases.append(_case(f"held-out-{i + 1}", "held_out", {"caller_goal": e["caller_goal"] or e["gap_summary"],
                                                             "caller_profile": member_profile(e["caller_ref"], e["call_id"]),
                                                             "source_call_id": e["call_id"]}))
    for i, sc in enumerate(p.payload.get("scenarios") or []):
        cases.append(_case(f"derived-{i + 1}", "derived", sc))
    repeats = LearningConfig.model_validate(base_cfg.get("learning") or {}).regression_repeats
    scenarios = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == p.agent_id, EvalScenario.enabled.is_(True))
                                 .order_by(EvalScenario.created_at))).all()
    for sc in scenarios:
        cases.append(_case(sc.name, "regression", test_suites.scenario_dict(sc), repeats, sc.id))
    return cases


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
        cases = await gather_cases(s, p, base_cfg)
    repeats = max([c["repeats"] for c in cases if c["type"] == "regression"] or [1])
    work = [(c, arm, k) for c in cases for arm in ("baseline", "candidate") for k in range(1, c["repeats"] + 1)]
    total, done = len(work), 0
    sem = asyncio.Semaphore(settings.ev_concurrency)
    lock = asyncio.Lock()
    tenant_name = tenant.name if tenant else tenant_id
    collected: list[dict[str, Any]] = []

    async def one(case: dict[str, Any], arm: str, repeat: int) -> None:
        nonlocal done
        cfg = base_cfg if arm == "baseline" else cand_cfg
        sc = case["scenario"]
        call_id, ok, failures, hard_fail, latencies = None, False, [], False, []
        async with sem:
            try:
                call_id, _ = await simulate(tenant_id, p.agent_id, run.baseline_version_id, tenant_name, cfg, sc["caller_goal"],
                                            sc["caller_profile"] or {}, persona=sc["persona"], memory=sc["memory"])
                async with sessionmaker()() as s2:
                    call = await s2.get(Call, call_id)
                    card = await scoring.score(s2, call, config=cfg, always_judge=True, goal=sc["caller_goal"], expected=sc["expected"])
                    events = list((await s2.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())
                    escalated = await s2.scalar(select(Escalation.id).where(Escalation.call_id == call_id)) is not None
                    failures = test_suites.check(sc, events, test_suites.outcome_of(escalated, getattr(card, "judge_outcome", None)),
                                                 card.checks, card.hard_fail)
                    hard_fail, latencies = card.hard_fail, list(card.measures.get("latencies_ms") or [])
                    await s2.commit()
                ok = not failures
            except Exception as exc:  # noqa: BLE001 - one failed case must not sink the run
                log.warning("eval case %s/%s/%s failed: %s", case["key"], arm, repeat, exc)
                failures = [f"The simulation failed: {str(exc)[:200]}"]
        async with sessionmaker()() as s3:
            s3.add(EvalResult(tenant_id=tenant_id, eval_run_id=run.id, case_key=case["key"], case_type=case["type"], arm=arm,
                              scenario_id=case["scenario_id"], repeat=repeat, scenario=sc, call_id=call_id, expected=sc["expected"],
                              passed=ok, failures=failures, judge={}))
            await s3.commit()
        async with lock:
            collected.append({"key": case["key"], "type": case["type"], "arm": arm, "repeat": repeat, "passed": ok,
                              "hard_fail": hard_fail, "latencies": latencies, "name": sc.get("name") or case["key"]})
            done += 1
            bus.publish(tenant_id, "insights", "eval.progress", {  # EV-06
                "proposal_id": p.id, "eval_run_id": run.id, "done": done, "total": total,
                "last": {"case_key": case["key"], "case_type": case["type"], "arm": arm, "repeat": repeat, "passed": ok,
                         "notes": "; ".join(failures)}})

    try:
        await asyncio.gather(*(one(c, a, k) for c, a, k in work))
        summary = evaluate_gate(collected, repeats)
        derived_base = defaultdict(bool)
        for r in collected:
            if r["type"] == "derived" and r["arm"] == "baseline" and r["passed"]:
                derived_base[r["key"]] = True
        async with sessionmaker()() as s:
            run_db = await s.get(EvalRun, run.id)
            p_db = await s.get(FixProposal, p.id)
            derived = [c for c in cases if c["type"] == "derived"]
            kept = [c["scenario"] for c in derived if not derived_base[c["key"]]]  # SL-09: a scenario the current version passes shows no gap
            p_db.payload = {**p_db.payload, "scenarios": kept}
            run_db.summary = {
                **summary, "derived_kept": len(kept), "derived_dropped": len(derived) - len(kept),
                "duration_s": round(time.perf_counter() - started, 1),
                # RV-14: a realtime agent is simulated on the text brain, so its scores approximate the spoken behaviour
                "pipeline": pipeline_of(base_cfg), "fidelity": "text_approximation" if pipeline_of(base_cfg) == "realtime" else "faithful",
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
