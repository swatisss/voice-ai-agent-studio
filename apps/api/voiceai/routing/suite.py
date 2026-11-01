"""The routing suite: a tenant's utterance → expected agent cases, run against the live router.

Spec: /architecture/capability-catalog.md (Routing suite, comparison runs), /architecture/supervisor-routing.md (Routing mode),
/api/rest-api.md (Evaluation: routing)
"""
from __future__ import annotations

import logging
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.models import Agent, EvalResult, EvalRun, Job, RoutingCase

log = logging.getLogger("voiceai.routing.suite")

MAX_CASES = 500
VAGUE = "?"  # a case whose right result is to ask (CAT-09)
# (tenant_id, scope, utterance) -> {agent_id, method, confidence, stage_b?, fallbacks?}
Decider = Callable[[str, str, str], Awaitable[dict[str, Any]]]


async def default_decider(tenant_id: str, scope: str, text: str) -> dict[str, Any]:
    """The supervisor's decision without clarification (/architecture/supervisor-routing.md)."""
    from voiceai.routing import supervisor

    return await supervisor.decide_for_suite(tenant_id, scope, text)


async def min_accuracy(s: AsyncSession, tenant_id: str) -> float:
    from voiceai.routing import front_desk

    return (await front_desk.load(s, tenant_id)).min_routing_accuracy


async def enqueue_run(s: AsyncSession, tenant_id: str, trigger: str, compare: bool = False) -> EvalRun | None:
    """A routing run unless one is already waiting (CAT-08). Caller commits. Returns None when one was waiting."""
    waiting = await s.scalar(select(Job).where(Job.tenant_id == tenant_id, Job.kind == "run_routing_suite", Job.status == "queued"))
    if waiting is not None:
        return None
    run = EvalRun(tenant_id=tenant_id, agent_id=None, kind="routing", trigger=trigger, status="running", repeats=1, summary={},
                  config={"compare": compare})
    s.add(run)
    await s.flush()
    await jobs.enqueue(s, tenant_id, "run_routing_suite", {"eval_run_id": run.id})
    return run


async def start_manual(s: AsyncSession, tenant_id: str, compare: bool = False) -> EvalRun:
    busy = await s.scalar(select(EvalRun.id).where(EvalRun.tenant_id == tenant_id, EvalRun.kind == "routing", EvalRun.status == "running"))
    if busy:
        raise ApiError(409, "run_in_progress", "A routing run is already in progress")
    run = await enqueue_run(s, tenant_id, "manual", compare)
    assert run is not None
    return run


def summarize(results: list[dict[str, Any]], pass_mark: float) -> dict[str, Any]:
    total = len(results)
    passed = sum(r["passed"] for r in results)
    by_agent: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "of": 0})
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for r in results:
        by_agent[r["expected"]]["of"] += 1
        by_agent[r["expected"]]["passed"] += int(r["passed"])
        confusion[r["expected"]][r["chosen"] or "none"] += 1
    latencies = sorted(r["latency_ms"] for r in results)
    accuracy = passed / total if total else None
    return {
        "cases": total, "passed": passed, "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "pass_mark": pass_mark, "passes": accuracy is not None and accuracy >= pass_mark,
        "by_agent": {a: {**v, "accuracy": round(v["passed"] / v["of"], 4)} for a, v in by_agent.items()},
        "confusion": {a: dict(c) for a, c in confusion.items()},
        "by_method": dict(Counter(r["method"] for r in results)),
        "clarification_rate": round(sum(r.get("unsure", False) for r in results) / total, 4) if total else None,
        "fallbacks": sum(bool(r.get("fallbacks")) for r in results),
        "latency_ms": {"p50": int(statistics.median(latencies)) if latencies else None,
                       "p95": latencies[max(0, int(round(0.95 * len(latencies))) - 1)] if latencies else None},
    }


async def run(eval_run_id: str, tenant_id: str, decider: Decider | None = None) -> dict[str, Any]:
    decider = decider or default_decider
    async with sessionmaker()() as s:
        run_row = await s.get(EvalRun, eval_run_id)
        if run_row is None or run_row.tenant_id != tenant_id:
            return {}
        cases = list((await s.scalars(select(RoutingCase).where(RoutingCase.tenant_id == tenant_id, RoutingCase.enabled.is_(True))
                                      .order_by(RoutingCase.created_at))).all())
        pass_mark = await min_accuracy(s, tenant_id)
    results: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        try:
            decision = await decider(tenant_id, case.scope, case.utterance)
        except Exception as exc:  # noqa: BLE001 - one case never stops the run
            log.warning("routing case %s failed: %s", case.id, exc)
            decision = {"agent_id": None, "method": "error", "confidence": None}
        latency = decision.get("latency_ms") or int((time.perf_counter() - started) * 1000)
        chosen = decision.get("agent_id")
        unsure = bool(decision.get("unsure"))
        passed = unsure if case.expected_agent_id == VAGUE else chosen == case.expected_agent_id
        results.append({"case_id": case.id, "utterance": case.utterance, "expected": case.expected_agent_id, "chosen": chosen,
                        "method": decision.get("method"), "confidence": decision.get("confidence"), "passed": passed,
                        "latency_ms": latency, "unsure": bool(decision.get("unsure")), "fallbacks": decision.get("fallbacks") or []})
    summary = summarize(results, pass_mark)
    async with sessionmaker()() as s:
        for r in results:
            s.add(EvalResult(tenant_id=tenant_id, eval_run_id=eval_run_id, case_key=r["case_id"], case_type="routing", arm="target",
                             expected="routing", passed=r["passed"], failures=[] if r["passed"] else [f"routed to {r['chosen'] or 'none'}"],
                             judge={k: r[k] for k in ("utterance", "expected", "chosen", "method", "confidence", "latency_ms", "fallbacks")}))
        row = await s.get(EvalRun, eval_run_id)
        row.status, row.summary, row.finished_at = "done", summary, utcnow()
        await s.commit()
    bus.publish(tenant_id, "evaluation", "routing_run.finished", {"eval_run_id": eval_run_id, "status": "done", "summary": summary})
    return summary


# ---------------------------------------------------------------- comparison runs (CAT-09)
async def compare_case(tenant_id: str, scope: str, text: str) -> dict[str, dict[str, Any]]:
    """Both routing modes on one request, from one Stage A ranking and at most one decision-model call."""
    from voiceai.routing import catalog, decision, front_desk, supervisor

    async with sessionmaker()() as s:
        fd = await front_desk.load(s, tenant_id)
        pool = await supervisor.candidates(s, tenant_id, scope)
        t0 = time.perf_counter()
        ranked = await catalog.stage_a(s, tenant_id, scope, text, set(pool))
        a_ms = (time.perf_counter() - t0) * 1000
    top = ranked[0]["agent_id"] if ranked else None
    win = supervisor.clear_winner(ranked, fd)
    out: dict[str, dict[str, Any]] = {"embedding": {"first": top, "decided": win["agent_id"] if win else None, "ms": a_ms}}
    if not decision.configured() or decision.blocked():
        out["decision_model"] = {"configured": False}
        return out
    t1 = time.perf_counter()
    choice, why = await supervisor.ask_model(text, None, ranked, pool, "text", fd)
    b_ms = (time.perf_counter() - t1) * 1000
    answered = choice.agent_id if (choice is not None and why is None) else None
    out["decision_model"] = {"configured": True, "first": answered or top, "decided": answered or (win["agent_id"] if win else None),
                             "ms": a_ms + b_ms, "fallback": why}
    return out


def compare_summary(rows: list[tuple[str, dict[str, dict[str, Any]]]], current: str) -> dict[str, Any]:
    out: dict[str, Any] = {"current": current}
    for mode in ("embedding", "decision_model"):
        got = [(want, r[mode]) for want, r in rows]
        if any(not g.get("configured", True) for _, g in got):
            out[mode] = {"configured": False}
            continue
        answerable = [(w, g) for w, g in got if w != VAGUE]
        vague = [g for w, g in got if w == VAGUE]
        decided = [(w, g) for w, g in answerable if g["decided"]]
        ms = sorted(g["ms"] for _, g in got)
        out[mode] = {
            "configured": True, "cases": len(got), "answerable": len(answerable),
            "right_first": sum(g["first"] == w for w, g in answerable),
            "decided_alone": len(decided), "right_when_decided": sum(g["decided"] == w for w, g in decided),
            "vague": len(vague), "vague_asked": sum(not g["decided"] for g in vague),
            "fallbacks": sum(1 for _, g in got if g.get("fallback")),
            "latency_ms": {"p50": int(statistics.median(ms)) if ms else None, "p95": int(ms[max(0, int(round(0.95 * len(ms))) - 1)]) if ms else None},
        }
    return out


async def run_compare(eval_run_id: str, tenant_id: str) -> dict[str, Any]:
    from voiceai.routing import front_desk

    async with sessionmaker()() as s:
        cases = list((await s.scalars(select(RoutingCase).where(RoutingCase.tenant_id == tenant_id, RoutingCase.enabled.is_(True))
                                      .order_by(RoutingCase.created_at))).all())
        current = (await front_desk.load(s, tenant_id)).routing_mode
    rows = []
    for case in cases:
        try:
            rows.append((case.expected_agent_id, await compare_case(tenant_id, case.scope, case.utterance)))
        except Exception as exc:  # noqa: BLE001 - one case never stops the run
            log.warning("routing comparison case %s failed: %s", case.id, exc)
    summary = {"compare": compare_summary(rows, current), "cases": len(rows)}
    async with sessionmaker()() as s:
        for (want, r), case in zip(rows, cases):
            s.add(EvalResult(tenant_id=tenant_id, eval_run_id=eval_run_id, case_key=case.id, case_type="routing", arm="compare",
                             expected="routing", passed=r["embedding"]["decided"] == want, failures=[],
                             judge={"utterance": case.utterance, "expected": want, **{m: v for m, v in r.items()}}))
        row = await s.get(EvalRun, eval_run_id)
        row.status, row.summary, row.finished_at = "done", summary, utcnow()
        await s.commit()
    bus.publish(tenant_id, "evaluation", "routing_run.finished", {"eval_run_id": eval_run_id, "status": "done", "summary": summary})
    return summary


@jobs.register("run_routing_suite")
async def run_routing_suite(tenant_id: str, payload: dict[str, Any]) -> None:
    try:
        async with sessionmaker()() as s:
            row = await s.get(EvalRun, payload["eval_run_id"])
            compare = bool((row.config or {}).get("compare")) if row else False
        if compare:
            await run_compare(payload["eval_run_id"], tenant_id)
            return
        await run(payload["eval_run_id"], tenant_id)
    except Exception as exc:
        async with sessionmaker()() as s:
            row = await s.get(EvalRun, payload["eval_run_id"])
            if row is not None:
                row.status, row.error, row.finished_at = "failed", str(exc)[:500], utcnow()
                await s.commit()
        raise


async def run_out(s: AsyncSession, row: EvalRun, with_results: bool = False) -> dict[str, Any]:
    out = {"id": row.id, "trigger": row.trigger, "status": row.status, "summary": row.summary or {}, "error": row.error,
           "created_at": row.created_at.isoformat(), "finished_at": row.finished_at.isoformat() if row.finished_at else None}
    if with_results:
        rows = (await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == row.id).order_by(EvalResult.created_at))).all()
        names = {a.id: a.name for a in (await s.scalars(select(Agent).where(Agent.tenant_id == row.tenant_id))).all()}
        out["results"] = [{"case_id": r.case_key, "utterance": r.judge.get("utterance"), "expected_agent_id": r.judge.get("expected"),
                           "expected_agent_name": names.get(r.judge.get("expected")), "chosen_agent_id": r.judge.get("chosen"),
                           "chosen_agent_name": names.get(r.judge.get("chosen")), "method": r.judge.get("method"),
                           "confidence": r.judge.get("confidence"), "passed": r.passed, "latency_ms": r.judge.get("latency_ms")} for r in rows]
        out["agent_names"] = names
    return out
