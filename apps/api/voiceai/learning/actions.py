"""Learning actions: each finding of evaluation and learning as one action with one next step, derived by every learning
run, closing itself when the finding clears; fix verification (did an approved fix hold?).

Spec: /architecture/learning-actions.md, /architecture/self-learning.md (step 0 Verify fixes, step 7 Actions)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.models import (
    Agent, AgentVersion, Call, CallAnalysis, CallFeedback, CallScorecard, CheckReview, Cluster, Escalation, EvalResult, EvalRun,
    EvalScenario, FixProposal, LearningAction,
)
from voiceai.schemas import LearningConfig

FIX_WINDOW = timedelta(days=14)  # SL-15: new signals after the fix that count
FIX_MIN_SIGNALS = 2
HELD_AFTER = timedelta(days=7)  # LA-09: a week without a signal and the fix held
CHECK_WINDOW = timedelta(days=7)
CHECK_MIN_DECIDED = 10
CHECK_FAIL_RATE = 0.2
REVIEW_SAMPLE = 10
MIN_ANSWER = 20
SEVERITY = {"high": 0, "medium": 1}
KIND_LABEL = {"goal_met": "Goal met", "grounded": "Grounded", "containment": "Containment"}


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def action_out(a: LearningAction, agent_name: str | None = None) -> dict[str, Any]:
    return {
        "id": a.id, "agent_id": a.agent_id, "agent_name": agent_name, "kind": a.kind, "key": a.key, "severity": a.severity,
        "status": a.status, "title": a.title, "detail": a.detail, "evidence": a.evidence or {}, "impact": a.impact,
        "closed_by": a.closed_by, "note": a.note, "closed_at": a.closed_at.isoformat() if a.closed_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None, "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def rank(items: list[LearningAction]) -> list[LearningAction]:
    """LA-08: severity, then impact, then oldest first."""
    return sorted(items, key=lambda a: (SEVERITY.get(a.severity, 9), -(a.impact or 0), a.created_at or utcnow()))


# ------------------------------------------------------------------ clusters: human answers and fixes
async def clusters_with_notes(s: AsyncSession, cluster_ids: list[str]) -> set[str]:
    """Clusters with at least one member call a specialist resolved with a note."""
    if not cluster_ids:
        return set()
    rows = (await s.execute(
        select(CallAnalysis.cluster_id).join(Escalation, Escalation.call_id == CallAnalysis.call_id)
        .where(CallAnalysis.cluster_id.in_(cluster_ids), Escalation.resolution_note.is_not(None), Escalation.resolution_note != "")
    )).all()
    return {r[0] for r in rows}


def needs_answer(c: Cluster, noted: set[str]) -> bool:
    """SL-16: knowledge is drafted only from what people said."""
    return c.root_cause == "missing_knowledge" and not (c.human_answer or "").strip() and c.id not in noted


async def _signal_times(s: AsyncSession, cluster_id: str) -> list[datetime]:
    """Start times of the cluster's member calls that carry a signal (escalated, thumbs down or quality signals)."""
    rows = (await s.execute(
        select(Call.started_at, CallAnalysis.outcome, CallAnalysis.signals, CallFeedback.rating)
        .join(Call, Call.id == CallAnalysis.call_id)
        .outerjoin(CallFeedback, CallFeedback.call_id == CallAnalysis.call_id)
        .where(CallAnalysis.cluster_id == cluster_id)
    )).all()
    return [_aware(t) for t, outcome, signals, rating in rows if outcome == "escalated" or rating == "down" or signals]


async def _last_fix(s: AsyncSession, cluster_id: str) -> FixProposal | None:
    return await s.scalar(select(FixProposal).where(FixProposal.cluster_id == cluster_id, FixProposal.status == "approved",
                                                    FixProposal.kind != "routing_update", FixProposal.decided_at.is_not(None))
                          .order_by(FixProposal.decided_at.desc()).limit(1))


async def fix_report(s: AsyncSession, c: Cluster, now: datetime | None = None) -> dict[str, Any] | None:
    """LA-09: signals per week before and since the last approved fix, and whether it held."""
    p = await _last_fix(s, c.id)
    if p is None:
        return None
    now, decided = now or utcnow(), _aware(p.decided_at)
    times = await _signal_times(s, c.id)
    before = sum(1 for t in times if decided - timedelta(days=28) <= t < decided)
    after = sum(1 for t in times if t >= decided)
    weeks = max((now - decided).total_seconds() / (7 * 86400), 1.0)
    reopened = _aware(c.reopened_at)
    held = False if reopened and reopened > decided else (True if not after and now - decided >= HELD_AFTER else None)
    version = await s.get(AgentVersion, p.resulting_version_id) if p.resulting_version_id else None
    return {"proposal_id": p.id, "version": version.version if version else None, "decided_at": decided.isoformat(),
            "before_per_week": round(before / 4, 2), "after_per_week": round(after / weeks, 2), "held": held}


async def cluster_extras(s: AsyncSession, clusters: list[Cluster]) -> dict[str, dict[str, Any]]:
    """The cluster fields of CP-0032 for the API: `human_answer`, `reopened_at`, `needs_answer`, `fix`."""
    noted = await clusters_with_notes(s, [c.id for c in clusters])
    out = {}
    for c in clusters:
        out[c.id] = {"human_answer": c.human_answer, "human_answer_by": c.human_answer_by,
                     "reopened_at": c.reopened_at.isoformat() if c.reopened_at else None,
                     "needs_answer": needs_answer(c, noted),
                     "fix": await fix_report(s, c) if c.status == "fixed" or c.reopened_at else None}
    return out


async def verify_fixes(s: AsyncSession, tenant_id: str, agent_id: str, now: datetime | None = None) -> list[str]:
    """Step 0 of a learning run (SL-15): a fixed cluster with ≥ 2 signals after its fix, within 14 days, is reopened."""
    now = now or utcnow()
    reopened = []
    for c in (await s.scalars(select(Cluster).where(Cluster.tenant_id == tenant_id, Cluster.agent_id == agent_id,
                                                     Cluster.status == "fixed"))).all():
        p = await _last_fix(s, c.id)
        if p is None:
            continue
        since = max(_aware(p.decided_at), now - FIX_WINDOW)
        if sum(1 for t in await _signal_times(s, c.id) if t >= since) >= FIX_MIN_SIGNALS:
            c.status, c.snoozed_until, c.reopened_at = "open", None, now
            reopened.append(c.id)
    return reopened


# ------------------------------------------------------------------ findings
async def _cluster_findings(s: AsyncSession, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
    from voiceai.routes.insights import cluster_out, recent_stats

    clusters = list((await s.scalars(select(Cluster).where(Cluster.tenant_id == tenant_id, Cluster.agent_id == agent_id))).all())
    stats = await recent_stats(s, tenant_id)
    noted = await clusters_with_notes(s, [c.id for c in clusters])
    out = []
    for c in clusters:
        info = cluster_out(c, stats)
        if c.reopened_at and c.status not in ("fixed", "ignored"):  # LA-01
            fix = await fix_report(s, c)
            out.append({"kind": "fix_not_holding", "key": f"fix_not_holding:{c.id}", "severity": "high",
                        "title": f"Fix did not hold: {c.name}",
                        "detail": f"{info['signal_count']} signals in 28 days; the fix in v{(fix or {}).get('version')} was approved "
                                  f"{(fix or {}).get('decided_at', '')[:10]}. Review the new draft, or roll back on the Versions tab.",
                        "evidence": {"cluster_id": c.id, **({k: fix[k] for k in ('before_per_week', 'after_per_week', 'version')} if fix else {})},
                        "impact": info["est_weekly_cost_usd"]})
        if info["ready_for_fix"] and needs_answer(c, noted):  # SL-16
            out.append({"kind": "answer_needed", "key": f"answer_needed:{c.id}", "severity": "high",
                        "title": f"Answer needed: {c.name}",
                        "detail": f"{info['signal_count']} callers asked this and no specialist note says what to tell them. "
                                  "Give the answer and a fix is drafted from it.",
                        "evidence": {"cluster_id": c.id}, "impact": info["est_weekly_cost_usd"]})
    return out


async def _check_findings(s: AsyncSession, agent: Agent, now: datetime) -> list[dict[str, Any]]:
    from voiceai.learning.nightly import calibrated_keys

    if not agent.published_version_id:
        return []
    version = await s.get(AgentVersion, agent.published_version_id)
    rows = (await s.execute(
        select(CallScorecard, Call.id).join(Call, Call.id == CallScorecard.call_id)
        .where(Call.agent_version_id == agent.published_version_id, Call.is_eval.is_(False), Call.started_at >= now - CHECK_WINDOW)
    )).all()
    calibrated = await calibrated_keys(s, agent.id)
    reviewed = defaultdict(set)
    for key, call_id in (await s.execute(select(CheckReview.check_key, CheckReview.call_id).where(CheckReview.agent_id == agent.id))).all():
        reviewed[key].add(call_id)
    by: dict[str, dict[str, Any]] = {}
    for card, call_id in rows:
        for c in card.checks or []:
            if c.get("verdict") not in ("pass", "fail"):
                continue
            e = by.setdefault(c["key"], {"text": c.get("text") or c["key"], "method": c.get("method"), "hard": bool(c.get("hard_gate")),
                                         "decided": 0, "failed": []})
            e["decided"] += 1
            if c["verdict"] == "fail":
                e["failed"].append(call_id)
    out = []
    for key, e in by.items():
        rate = len(e["failed"]) / e["decided"] if e["decided"] else 0
        if e["decided"] < CHECK_MIN_DECIDED or rate < CHECK_FAIL_RATE - 1e-9:
            continue
        review = e["method"] == "judge" and key not in calibrated  # LA-04: people's labels calibrate the judge
        listed = [c for c in e["failed"] if c not in reviewed[key]][:REVIEW_SAMPLE] if review else e["failed"][:REVIEW_SAMPLE]
        if review and not listed:
            continue  # every failing call is reviewed: the next step is done
        pct = round(rate * 100)
        title = (f"Review {len(listed)} calls: {e['text']}" if review else f"Check failing on {pct} % of calls: {e['text']}")[:300]
        detail = (f"Fails on {len(e['failed'])} of {e['decided']} calls of v{version.version} in 7 days; the judge is not calibrated "
                  "for this agent yet, so review these calls (your labels calibrate it)." if review else
                  f"Fails on {len(e['failed'])} of {e['decided']} calls of v{version.version} in 7 days.")
        out.append({"kind": "check_failing", "key": f"check_failing:{version.id}:{key}", "severity": "high" if e["hard"] else "medium",
                    "title": title, "detail": detail, "impact": float(len(e["failed"])),
                    "evidence": {"check_key": key, "version_id": version.id, "call_ids": listed, "rate": round(rate, 2),
                                 "decided": e["decided"], "needs_review": review}})
    return out


async def _drift_findings(s: AsyncSession, agent: Agent) -> list[dict[str, Any]]:
    from voiceai.learning import score_report

    if not agent.published_version_id:
        return []
    summary = await score_report.summary(s, agent.tenant_id, agent.id, days=90, include_seed=True)
    v = next((x for x in summary["versions"] if x["version_id"] == agent.published_version_id), None)
    out = []
    for metric in (v or {}).get("drift") or []:
        out.append({"kind": "drift", "key": f"drift:{agent.published_version_id}:{metric}", "severity": "high",
                    "title": f"{KIND_LABEL.get(metric, metric)} drifted on v{v['version']}",
                    "detail": "Lower in the last 7 days than in this version's first week (10 points or more).",
                    "evidence": {"version_id": agent.published_version_id, "metric": metric}, "impact": float(v.get("scored") or 0)})
    return out


async def _scenario_findings(s: AsyncSession, agent: Agent) -> list[dict[str, Any]]:
    if not agent.published_version_id:
        return []
    run = await s.scalar(select(EvalRun).where(EvalRun.agent_id == agent.id, EvalRun.kind == "suite", EvalRun.status == "done",
                                               EvalRun.baseline_version_id == agent.published_version_id)
                         .order_by(EvalRun.created_at.desc()).limit(1))
    if run is None:
        return []
    version = await s.get(AgentVersion, agent.published_version_id)
    enabled = {sc.id: sc for sc in (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == agent.id,
                                                                                 EvalScenario.enabled.is_(True)))).all()}
    by: dict[str, list[bool]] = defaultdict(list)
    for r in (await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == run.id))).all():
        if r.scenario_id in enabled:
            by[r.scenario_id].append(bool(r.passed))
    out = []
    for sid, results in by.items():
        n, k = sum(results), len(results)
        if n == k:
            continue
        flaky = ", flaky" if n else ""
        out.append({"kind": "scenario_failing", "key": f"scenario_failing:{version.id}:{sid}", "severity": "medium",
                    "title": f"Test scenario failing on v{version.version}: {enabled[sid].name} ({n}/{k}{flaky})"[:300],
                    "detail": f"In the latest test run of the live version it passed {n} of {k} runs.",
                    "evidence": {"scenario_id": sid, "test_run_id": run.id, "version_id": version.id, "passed": n, "runs": k},
                    "impact": float(k - n)})
    return out


# ------------------------------------------------------------------ lifecycle
async def derive(s: AsyncSession, tenant_id: str, agent_id: str, now: datetime | None = None) -> dict[str, int]:
    """Step 7 of a learning run: open new findings, refresh open ones, resolve cleared ones (LA-01…LA-07). Caller commits."""
    now = now or utcnow()
    agent = await s.get(Agent, agent_id)
    findings = [*await _cluster_findings(s, tenant_id, agent_id), *await _check_findings(s, agent, now),
                *await _drift_findings(s, agent), *await _scenario_findings(s, agent)]
    rows = list((await s.scalars(select(LearningAction).where(LearningAction.tenant_id == tenant_id, LearningAction.agent_id == agent_id)
                                 .order_by(LearningAction.created_at))).all())
    open_by = {a.key: a for a in rows if a.status == "open"}
    suppressed = {a.key for a in rows if a.status in ("done", "dismissed") and a.suppressed_until and _aware(a.suppressed_until) > now}
    changed: list[LearningAction] = []
    opened = resolved = 0
    keys = set()
    for f in findings:
        keys.add(f["key"])
        a = open_by.get(f["key"])
        if a is not None:
            a.title, a.detail, a.evidence, a.impact, a.severity = f["title"], f["detail"], f["evidence"], f["impact"], f["severity"]
            changed.append(a)
        elif f["key"] not in suppressed:  # LA-07
            a = LearningAction(tenant_id=tenant_id, agent_id=agent_id, **f)
            s.add(a)
            changed.append(a)
            opened += 1
    for key, a in open_by.items():
        if key not in keys:
            a.status, a.closed_at, a.closed_by = "resolved", now, "learning run"
            changed.append(a)
            resolved += 1
    await s.flush()
    for a in changed:
        bus.publish(tenant_id, "insights", "action.updated", action_out(a, agent.name if agent else None))
    still_open = sum(1 for a in rows if a.status == "open" and a.key in keys) + opened
    return {"opened": opened, "resolved": resolved, "open": still_open}


async def get_action(s: AsyncSession, tenant_id: str, action_id: str) -> LearningAction:
    a = await s.scalar(select(LearningAction).where(LearningAction.id == action_id, LearningAction.tenant_id == tenant_id))
    if a is None:
        raise ApiError(404, "action_not_found", "Action not found")
    return a


async def close(s: AsyncSession, a: LearningAction, status: str, by: str, note: str | None) -> LearningAction:
    """Done or dismissed by a person; the same finding stays closed for `learning.snooze_days` (LA-07)."""
    if a.status != "open":
        raise ApiError(409, "invalid_state", f"Action is {a.status}")
    agent = await s.get(Agent, a.agent_id)
    days = LearningConfig.model_validate(((agent.draft_config if agent else {}) or {}).get("learning") or {}).snooze_days
    now = utcnow()
    a.status, a.closed_by, a.note, a.closed_at, a.suppressed_until = status, (by or "Reviewer")[:120], note, now, now + timedelta(days=days)
    await s.commit()
    bus.publish(a.tenant_id, "insights", "action.updated", action_out(a, agent.name if agent else None))
    return a


async def answer(s: AsyncSession, a: LearningAction, text: str, by: str) -> LearningAction:
    """LA-02: the reviewer's answer becomes the cluster's evidence; a fix is drafted and evaluated from it."""
    if a.status != "open" or a.kind != "answer_needed":
        raise ApiError(409, "invalid_state", "Only an open 'answer needed' action takes an answer")
    if len((text or "").strip()) < MIN_ANSWER:
        raise ApiError(422, "answer_too_short", f"The answer must be at least {MIN_ANSWER} characters")
    cluster = await s.get(Cluster, (a.evidence or {}).get("cluster_id") or "")
    if cluster is None:
        raise ApiError(409, "invalid_state", "The cluster of this action no longer exists")
    cluster.human_answer, cluster.human_answer_by = text.strip(), (by or "Reviewer")[:120]
    await jobs.enqueue(s, a.tenant_id, "draft_and_evaluate", {"cluster_id": cluster.id})
    return await close(s, a, "done", by, "Answered")


@jobs.register("draft_and_evaluate")
async def draft_and_evaluate(tenant_id: str, payload: dict[str, Any]) -> None:
    from voiceai.learning import evaluate, propose

    async with sessionmaker()() as s:
        cluster = await s.scalar(select(Cluster).where(Cluster.id == payload["cluster_id"], Cluster.tenant_id == tenant_id))
        if cluster is None or cluster.status != "open":
            return
        p = await propose.draft(s, tenant_id, cluster, origin="manual")
        await s.commit()
        bus.publish(tenant_id, "insights", "proposal.updated", propose.proposal_summary(p))
        await evaluate.start_eval(s, tenant_id, p)  # queues run_eval; the proposal reaches the inbox with its gate

