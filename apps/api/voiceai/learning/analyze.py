"""Post-call analysis and gap clustering.

Spec: /architecture/fleet-learning.md (1. Call analysis, 2. Clustering), /prompts/call-analysis.md, /prompts/cluster-naming.md
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core import jobs, prompts
from voiceai.core.config import get_settings
from voiceai.core.db import sessionmaker, utcnow
from voiceai.core.events import bus
from voiceai.core.embeddings import embed_one
from voiceai.core.llm.gateway import gateway
from voiceai.core.tables import AgentVersion, Call, CallAnalysis, CallEvent, CallFeedback, Cluster, Escalation
from voiceai.runtime.escalation import transcript_lines
from voiceai.schemas import FIXABLE, AnalysisOut, ClusterName

log = logging.getLogger("voiceai.learning")


def cluster_summary(c: Cluster) -> dict[str, Any]:
    from voiceai.learning.impact import impact

    return {
        "id": c.id, "agent_id": c.agent_id, "name": c.name, "description": c.description, "root_cause": c.root_cause,
        "fixable": c.fixable, "call_count": c.call_count, "escalation_count": c.escalation_count, "status": c.status,
        "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None,
        "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
        **impact(c),
    }


def _escalation_text(esc: Escalation | None) -> str:
    if not esc:
        return "none"
    parts = [f"category={esc.reason_category}", f"detail={esc.reason_detail}"]
    if esc.disposition:
        parts.append(f"disposition={esc.disposition}")
    if esc.resolution_note:
        parts.append(f"human resolution note: {esc.resolution_note}")
    return "; ".join(parts)


def feedback_text(fb: CallFeedback | None) -> str:
    """The `caller_feedback` input of the call-analysis prompt (FB-03)."""
    if fb is None:
        return "none"
    if fb.rating == "up":
        return "thumbs up"
    return f"thumbs down: {fb.comment or ''}".rstrip()


def apply_feedback(out: AnalysisOut, fb: CallFeedback | None) -> None:
    """A thumbs-down call is always a learning candidate: never root cause `none`, never an empty gap summary (FB-03)."""
    if fb is None or fb.rating != "down":
        return
    if out.root_cause == "none":
        out.root_cause = "agent_error"
    if not out.gap_summary.strip():
        out.gap_summary = (fb.comment or "").strip()[:200] or "The caller was not satisfied with the help they received"


@jobs.register("analyze_call")
async def analyze_call(tenant_id: str, payload: dict[str, Any]) -> None:
    call_id = payload["call_id"]
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
        if not call or call.is_eval:
            return
        events = list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        fb = await s.scalar(select(CallFeedback).where(CallFeedback.call_id == call_id))
        version = await s.get(AgentVersion, call.agent_version_id)
        tools = (version.config if version else {}).get("tools", [])
        state = (call.meta or {}).get("state", {})
        no_answers = state.get("no_answer_queries", [])
        prompt = prompts.render(
            "call-analysis",
            tools_available="\n".join(f"- {t['name']}: {t.get('description', '')}" for t in tools) or "- (none)",
            search_results_summary=f"{len(no_answers)} ({'; '.join(no_answers)})" if no_answers else "0",
            escalation=_escalation_text(esc),
            caller_feedback=feedback_text(fb),
            transcript=transcript_lines(events) or "(empty)",
        )
        out, _ = await gateway().complete_json("analysis", [{"role": "user", "content": prompt}], AnalysisOut)
        if esc and out.outcome != "escalated":
            out.outcome = "escalated"
        if out.outcome == "resolved":
            out.root_cause = "none"
        apply_feedback(out, fb)  # after the resolved rule: a disliked resolved call keeps a cause
        await save_analysis(s, call, out, source="llm")
        await s.commit()


async def save_analysis(s: AsyncSession, call: Call, out: AnalysisOut, source: str) -> CallAnalysis:
    """Upsert the analysis (FL-01), set call outcome, embed + cluster escalations."""
    analysis = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call.id))
    if analysis is None:
        analysis = CallAnalysis(tenant_id=call.tenant_id, call_id=call.id, agent_id=call.agent_id, outcome=out.outcome)
        s.add(analysis)
    for field in ("outcome", "intent", "root_cause", "gap_summary", "caller_goal", "resolution_summary", "sentiment_start", "sentiment_end"):
        setattr(analysis, field, getattr(out, field))
    analysis.fixable = out.root_cause in FIXABLE
    analysis.source = source
    call.outcome = out.outcome
    await s.flush()
    disliked = await s.scalar(select(CallFeedback.rating).where(CallFeedback.call_id == call.id)) == "down"
    if (out.outcome == "escalated" or disliked) and out.gap_summary.strip():  # FB-04: a thumbs down is a candidate like an escalation
        analysis.embedding = await embed_one(out.gap_summary)
        await assign_cluster(s, analysis, when=call.started_at)
    bus.publish(call.tenant_id, "insights", "analysis.created",
                {"call_id": call.id, "outcome": analysis.outcome, "root_cause": analysis.root_cause, "cluster_id": analysis.cluster_id})
    return analysis


async def assign_cluster(s: AsyncSession, analysis: CallAnalysis, when=None) -> Cluster:  # noqa: ANN001
    """Nearest-centroid assignment or a new LLM-named cluster (FL-02, FL-03)."""
    vec = np.array(analysis.embedding, dtype=np.float32)
    clusters = list((await s.scalars(
        select(Cluster).where(Cluster.agent_id == analysis.agent_id, Cluster.tenant_id == analysis.tenant_id, Cluster.status != "ignored")
    )).all())
    best, best_score = None, -1.0
    for c in clusters:
        score = float(np.dot(vec, np.array(c.centroid, dtype=np.float32)))
        if score > best_score:
            best, best_score = c, score
    if best is not None and best_score >= get_settings().cluster_threshold:
        cluster = best
        n = max(cluster.call_count, 1)  # members, escalated or thumbs-down
        centroid = (np.array(cluster.centroid, dtype=np.float32) * n + vec) / (n + 1)
        cluster.centroid = (centroid / (np.linalg.norm(centroid) or 1.0)).round(6).tolist()
    else:
        name = await name_cluster([analysis.gap_summary], [analysis.root_cause])
        cluster = Cluster(
            tenant_id=analysis.tenant_id, agent_id=analysis.agent_id, name=name.name, description=name.description,
            root_cause=analysis.root_cause, fixable=analysis.root_cause in FIXABLE, centroid=vec.round(6).tolist(),
        )
        s.add(cluster)
        await s.flush()
    analysis.cluster_id = cluster.id
    await s.flush()
    await refresh_stats(s, cluster)
    bus.publish(cluster.tenant_id, "insights", "cluster.updated", cluster_summary(cluster))
    return cluster


async def name_cluster(gaps: list[str], root_causes: list[str]) -> ClusterName:
    try:
        prompt = prompts.render(
            "cluster-naming",
            gap_summaries="\n".join(f"- {g}" for g in gaps[:5]),
            root_causes=", ".join(f"{k}: {v}" for k, v in Counter(root_causes).items()),
        )
        out, _ = await gateway().complete_json("drafting", [{"role": "user", "content": prompt}], ClusterName)
        return out
    except Exception as exc:  # noqa: BLE001 - naming must never block clustering
        log.warning("cluster naming failed: %s", exc)
        return ClusterName(name=gaps[0][:60] if gaps else "Unnamed cluster", description=gaps[0] if gaps else "")


async def refresh_stats(s: AsyncSession, cluster: Cluster) -> None:
    rows = (await s.execute(
        select(CallAnalysis.root_cause, CallAnalysis.outcome, Call.started_at)
        .join(Call, Call.id == CallAnalysis.call_id)
        .where(CallAnalysis.cluster_id == cluster.id)
    )).all()
    cluster.call_count = len(rows)
    cluster.escalation_count = sum(1 for r in rows if r.outcome == "escalated")
    if rows:
        cluster.first_seen_at = min(r.started_at for r in rows)
        cluster.last_seen_at = max(r.started_at for r in rows)
        majority = Counter(r.root_cause for r in rows).most_common(1)[0][0]
        cluster.root_cause = majority
        cluster.fixable = majority in FIXABLE
    cluster.updated_at = utcnow()
