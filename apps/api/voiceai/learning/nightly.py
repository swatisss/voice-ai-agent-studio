"""The nightly self-learning run: external signals, re-analysis, ready clusters, drafting under a cap, the gate, a report.
It only ever proposes: nothing here approves, publishes or edits an agent.

Spec: /architecture/self-learning.md (Nightly run, Guardrails)
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.learning import analyze, evaluate, gate, propose, score_report
from voiceai.models import (
    Agent, AgentVersion, Call, CallAnalysis, CallEvent, CallFeedback, CallScorecard, CheckReview, Cluster, Escalation, EvalRun,
    LearningRun, Tenant,
)
from voiceai.schemas import LearningConfig

log = logging.getLogger("voiceai.learning")
LOOKBACK = timedelta(days=7)
SIGNAL_KINDS = ("escalated", "thumbs_down", "no_answer", "tool_error", "hard_fail", "calibrated_judge_fail")


def run_out(r: LearningRun) -> dict[str, Any]:
    return {"id": r.id, "trigger": r.trigger, "status": r.status, "since": r.since.isoformat() if r.since else None,
            "summary": r.summary or {}, "error": r.error, "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


async def calibrated_keys(s: AsyncSession, agent_id: str) -> set[str]:
    """Judge checks reviewers have calibrated for this agent (CP-0020); only their failures count as signals (SL-03)."""
    by: dict[str, list[CheckReview]] = defaultdict(list)
    for r in (await s.scalars(select(CheckReview).where(CheckReview.agent_id == agent_id))).all():
        by[r.check_key].append(r)
    return {k for k, rows in by.items() if score_report.calibration(rows)["calibrated"]}


def signals_of(events: list[CallEvent], card: CallScorecard | None, escalated: bool, disliked: bool,
               calibrated: set[str]) -> list[tuple[str, str]]:
    """(kind, text) for each external signal of a call (/architecture/self-learning.md, Nightly run step 1)."""
    out: list[tuple[str, str]] = []
    if escalated:
        out.append(("escalated", "Escalated to a human"))
    if disliked:
        out.append(("thumbs_down", "The caller gave a thumbs down"))
    for e in events:
        data = e.data or {}
        if e.kind != "tool_result":
            continue
        if data.get("name") == "search_knowledge":
            retrieval = data.get("retrieval") or {}
            if retrieval.get("no_answer") or (data.get("result") or {}).get("no_answer"):
                out.append(("no_answer", f"Knowledge search found nothing for: {retrieval.get('query') or 'a question'}"))
        elif not data.get("ok", True):
            out.append(("tool_error", f"Tool {data.get('name')} failed"))
    for c in (card.checks if card else []):
        if c["verdict"] != "fail":
            continue
        if c["method"] == "code" and c["hard_gate"]:
            out.append(("hard_fail", f"Check failed: {c['text']}"))
        elif c["method"] == "judge" and c["key"] in calibrated:
            out.append(("calibrated_judge_fail", f"Check failed: {c['text']}"))
    return out


async def start_run(s: AsyncSession, tenant_id: str, trigger: str) -> LearningRun:
    """SL-01: one running learning run per tenant. Caller commits."""
    running = await s.scalar(select(LearningRun.id).where(LearningRun.tenant_id == tenant_id, LearningRun.status == "running"))
    if running:
        raise ApiError(409, "run_in_progress", "A learning run is already running")
    run = LearningRun(tenant_id=tenant_id, trigger=trigger)
    s.add(run)
    await s.flush()
    key = f"nightly_learning:{tenant_id}:{utcnow().date().isoformat()}" if trigger == "nightly" else None
    await jobs.enqueue(s, tenant_id, "nightly_learning", {"learning_run_id": run.id}, dedupe_key=key)
    return run


async def schedule_nightly(now: datetime | None = None, running_since: datetime | None = None) -> int:
    """Called by the idle worker: start today's nightly run for each tenant once the hour has passed while the service
    was running (SL-01). A night missed while the service was down is not caught up at start, so starting a demo never
    launches the loop by itself."""
    now = now or utcnow()
    if now.hour < get_settings().learning_nightly_hour_utc:
        return 0
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    if running_since is not None and running_since > day_start + timedelta(hours=get_settings().learning_nightly_hour_utc):
        return 0
    started = 0
    async with sessionmaker()() as s:
        for tenant_id in (await s.scalars(select(Tenant.id))).all():
            done_today = await s.scalar(select(LearningRun.id).where(LearningRun.tenant_id == tenant_id, LearningRun.trigger == "nightly",
                                                                    LearningRun.started_at >= day_start))
            if done_today:
                continue
            try:
                await start_run(s, tenant_id, "nightly")
                started += 1
            except ApiError:
                continue
        await s.commit()
    return started


async def _agent_pass(tenant_id: str, agent: Agent, since: datetime) -> dict[str, Any]:
    """One agent's night: signals → re-analysis → ready clusters → up to N proposals, each gated."""
    report: dict[str, Any] = {"agent_name": agent.name, "calls_reviewed": 0, "signals": dict.fromkeys(SIGNAL_KINDS, 0),
                              "reanalysed": 0, "ready_clusters": 0, "drafted": 0, "passed": 0, "proposals": []}
    async with sessionmaker()() as s:
        version = await s.get(AgentVersion, agent.published_version_id)
        learning = LearningConfig.model_validate(((version.config if version else {}) or {}).get("learning") or {})
        if not learning.nightly:
            report["skipped"] = "learning is off for this agent"
            return report
        calls = list((await s.scalars(select(Call).where(
            Call.agent_id == agent.id, Call.tenant_id == tenant_id, Call.is_eval.is_(False), Call.is_seed.is_(False),
            Call.channel != "simulation", Call.ended_at.is_not(None), Call.ended_at >= since))).all())
        calibrated = await calibrated_keys(s, agent.id)
        report["calls_reviewed"] = len(calls)
        to_reanalyse: list[tuple[str, list[str]]] = []
        for call in calls:
            events = list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.seq))).all())
            card = await s.scalar(select(CallScorecard).where(CallScorecard.call_id == call.id))
            escalated = call.outcome == "escalated" or await s.scalar(select(Escalation.id).where(Escalation.call_id == call.id)) is not None
            disliked = await s.scalar(select(CallFeedback.rating).where(CallFeedback.call_id == call.id)) == "down"
            found = signals_of(events, card, escalated, disliked, calibrated)
            for kind, _ in found:
                report["signals"][kind] += 1
            quality = [text for kind, text in found if kind not in ("escalated", "thumbs_down")]
            analysis = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call.id))
            if quality and not escalated and not disliked and analysis is not None and analysis.root_cause == "none" and not analysis.signals:
                to_reanalyse.append((call.id, quality))
    for call_id, quality in to_reanalyse:  # SL-02: like a thumbs down, so the call joins a cluster
        await analyze.analyze_call(tenant_id, {"call_id": call_id, "signals": quality})
        report["reanalysed"] += 1

    from voiceai.routes.insights import cluster_out, recent_stats

    async with sessionmaker()() as s:
        stats = await recent_stats(s, tenant_id)
        clusters = (await s.scalars(select(Cluster).where(Cluster.agent_id == agent.id, Cluster.tenant_id == tenant_id))).all()
        ready = sorted((cluster_out(c, stats) for c in clusters), key=lambda c: -c["est_weekly_cost_usd"])
        ready = [c for c in ready if c["ready_for_fix"]]
        report["ready_clusters"] = len(ready)
        chosen = [c["id"] for c in ready[: learning.max_proposals_per_night]]  # SL-04
    for cluster_id in chosen:
        try:
            async with sessionmaker()() as s:
                cluster = await s.get(Cluster, cluster_id)
                p = await propose.draft(s, tenant_id, cluster, origin="nightly")
                await s.commit()
                bus.publish(tenant_id, "insights", "proposal.updated", propose.proposal_summary(p))
                run = await evaluate.start_eval(s, tenant_id, p, enqueue=False)
            await gate.run_eval(tenant_id, {"proposal_id": p.id, "eval_run_id": run.id})
            async with sessionmaker()() as s:
                summary = (await s.get(EvalRun, run.id)).summary or {}
            passed = bool((summary.get("gate") or {}).get("passed"))
            report["drafted"] += 1
            report["passed"] += passed
            report["proposals"].append({"id": p.id, "title": p.title, "kind": p.kind, "gate_passed": passed})
        except Exception as exc:  # noqa: BLE001 - one cluster must not stop the night
            log.warning("nightly draft for cluster %s failed: %s", cluster_id, exc)
            report.setdefault("errors", []).append(f"{cluster_id}: {str(exc)[:200]}")
    return report


@jobs.register("nightly_learning")
async def nightly_learning(tenant_id: str, payload: dict[str, Any]) -> None:
    async with sessionmaker()() as s:
        run = await s.scalar(select(LearningRun).where(LearningRun.id == payload["learning_run_id"], LearningRun.tenant_id == tenant_id))
        if run is None or run.status != "running":
            return
        last = await s.scalar(select(LearningRun.finished_at).where(LearningRun.tenant_id == tenant_id, LearningRun.status == "done")
                              .order_by(LearningRun.finished_at.desc()).limit(1))
        since = max(last, utcnow() - LOOKBACK) if last else utcnow() - LOOKBACK
        run.since = since
        await s.commit()
        agents = list((await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id, Agent.published_version_id.is_not(None))
                                       .order_by(Agent.created_at))).all())
    report: dict[str, Any] = {"agents": {}}
    try:
        for agent in agents:
            report["agents"][agent.id] = await _agent_pass(tenant_id, agent, since)
        totals = Counter()
        for a in report["agents"].values():
            for k in ("calls_reviewed", "reanalysed", "ready_clusters", "drafted", "passed"):
                totals[k] += a[k]
            for k, n in a["signals"].items():
                totals[f"signals.{k}"] += n
            totals["failed_drafts"] += len(a.get("errors", []))  # shown, so a broken run is never silent
        report["totals"] = dict(totals)
        status, error = "done", None
    except Exception as exc:  # noqa: BLE001
        log.exception("nightly learning failed for %s", tenant_id)
        status, error = "failed", str(exc)[:1000]
    async with sessionmaker()() as s:
        row = await s.get(LearningRun, payload["learning_run_id"])
        row.status, row.summary, row.error, row.finished_at = status, report, error, utcnow()
        await s.commit()
        bus.publish(tenant_id, "insights", "learning.run.finished",  # SL-12
                    {"learning_run_id": row.id, "status": status, "trigger": row.trigger, "summary": report})
