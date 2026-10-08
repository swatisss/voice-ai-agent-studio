"""The dashboard read model: containment, cost, latency and root causes.

Spec: /ui/dashboard.md, /api/rest-api.md (Dashboard), /product/vision.md (Success metrics)

This module owns no tables. It exists so that reading across modules has a name and a home: the
dashboard needs cluster cards from fleet learning, and it gets them through that module's contract
rather than by calling its route handler, which is what it used to do.
"""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.config import get_settings
from voiceai.core.tables import AgentVersion, Call, CallAnalysis
from voiceai.modules.learning.contract import top_clusters

RECENT_WEEKS = 6
RECENT_VERSIONS = 6
TOP_CLUSTERS = 5


async def summary(s: AsyncSession, tenant_id: str, agent_id: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    q = (select(Call, CallAnalysis.root_cause)
         .outerjoin(CallAnalysis, CallAnalysis.call_id == Call.id)
         .where(Call.tenant_id == tenant_id, Call.is_eval.is_(False), Call.ended_at.is_not(None)))  # MT-04, EV-03
    if agent_id:
        q = q.where(Call.agent_id == agent_id)
    rows = (await s.execute(q)).all()
    calls = [c for c, _ in rows]
    resolved = sum(1 for c in calls if c.outcome == "resolved")
    escalated = sum(1 for c in calls if c.outcome == "escalated")
    abandoned = sum(1 for c in calls if c.outcome == "abandoned")
    decided = resolved + escalated
    latencies = [c.latency_p50_ms for c in calls if c.latency_p50_ms]
    costs = [c.llm_cost_usd for c in calls if c.llm_cost_usd]

    weekly: dict[str, dict[str, int]] = {}
    for c in calls:
        start = (c.started_at - timedelta(days=c.started_at.weekday())).date().isoformat()
        w = weekly.setdefault(start, {"calls": 0, "resolved": 0, "escalated": 0})
        w["calls"] += 1
        w["resolved"] += c.outcome == "resolved"
        w["escalated"] += c.outcome == "escalated"
    weekly_out = [
        {"week_start": k, "calls": v["calls"],
         "containment_rate": round(v["resolved"] / (v["resolved"] + v["escalated"]), 4) if (v["resolved"] + v["escalated"]) else None}
        for k, v in sorted(weekly.items())
    ][-RECENT_WEEKS:]

    by_cause = Counter(rc for c, rc in rows if c.outcome == "escalated" and rc)
    vq = select(AgentVersion).where(AgentVersion.tenant_id == tenant_id).order_by(AgentVersion.created_at.desc()).limit(RECENT_VERSIONS)
    if agent_id:
        vq = vq.where(AgentVersion.agent_id == agent_id)
    versions = (await s.scalars(vq)).all()
    top = await top_clusters(s, tenant_id, agent_id, limit=TOP_CLUSTERS)
    return {
        "totals": {
            "calls": len(calls), "resolved": resolved, "escalated": escalated, "abandoned": abandoned,
            "containment_rate": round(resolved / decided, 4) if decided else None,  # UI-03
            "cost_saved_usd": round(resolved * (settings.human_cost_per_call - settings.ai_cost_per_call), 2),
            "avg_llm_cost_usd": round(sum(costs) / len(costs), 5) if costs else 0,
            "latency_p50_ms": int(statistics.median(latencies)) if latencies else None,
        },
        "weekly": weekly_out,
        "by_root_cause": [{"root_cause": k, "count": v} for k, v in by_cause.most_common()],
        "top_clusters": top,
        "recent_versions": [{"id": v.id, "agent_id": v.agent_id, "version": v.version, "change_note": v.change_note,
                             "source_proposal_id": v.source_proposal_id, "created_at": v.created_at.isoformat()} for v in versions],
    }
