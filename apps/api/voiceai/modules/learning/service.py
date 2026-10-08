"""Reading clusters: the 28-day signal rollup, the cluster card, and the readiness gate.

Spec: /architecture/fleet-learning.md, /api/rest-api.md (Insights)

This is the read model behind both the Insights pages and the dashboard's top-clusters tile. It
lives here, behind `contract.top_clusters`, because the dashboard used to import the Insights route
handler and call it as a function - which would break outright the day the two were separate
services.

`readiness` exists because three handlers only needed one boolean and were each paying for a
tenant-wide aggregate over every cluster to get it.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import utcnow
from voiceai.core.tables import Call, CallAnalysis, CallFeedback, Cluster
from voiceai.modules.learning.analyze import cluster_summary
from voiceai.modules.learning.domain import impact


_NO_STATS = {"escalations": 0, "dislikes": 0, "signals": 0}


async def _recent_stats(s: AsyncSession, tenant_id: str) -> dict[str, dict[str, int]]:
    """Per cluster, over the last 28 days: escalations, thumbs-down calls, and distinct signals (a call that is both counts once)."""
    since = utcnow() - timedelta(days=28)
    rows = (await s.execute(
        select(CallAnalysis.cluster_id, CallAnalysis.outcome, CallFeedback.rating)
        .join(Call, Call.id == CallAnalysis.call_id)
        .outerjoin(CallFeedback, CallFeedback.call_id == CallAnalysis.call_id)
        .where(CallAnalysis.tenant_id == tenant_id, Call.started_at >= since, CallAnalysis.cluster_id.is_not(None))
    )).all()
    stats: dict[str, dict[str, int]] = {}
    for cid, outcome, rating in rows:
        st = stats.setdefault(cid, dict(_NO_STATS))
        escalated, disliked = outcome == "escalated", rating == "down"
        st["escalations"] += escalated
        st["dislikes"] += disliked
        st["signals"] += escalated or disliked
    return stats


def _cluster_out(c: Cluster, stats: dict[str, dict[str, int]]) -> dict[str, Any]:
    st = stats.get(c.id, _NO_STATS)
    return {
        **cluster_summary(c), **impact(c, st["escalations"], recent_signals=st["signals"]),
        "escalations_28d": st["escalations"], "dislike_count": st["dislikes"], "signal_count": st["signals"],
    }


async def cluster_cards(s: AsyncSession, tenant_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
    """Every cluster of a tenant as a card, costliest first."""
    q = select(Cluster).where(Cluster.tenant_id == tenant_id)
    if agent_id:
        q = q.where(Cluster.agent_id == agent_id)
    recent = await _recent_stats(s, tenant_id)
    cards = [_cluster_out(c, recent) for c in (await s.scalars(q)).all()]
    cards.sort(key=lambda c: (-c["est_weekly_cost_usd"], c["name"]))
    return cards


async def cluster_card(s: AsyncSession, tenant_id: str, cluster: Cluster) -> dict[str, Any]:
    return _cluster_out(cluster, await _recent_stats(s, tenant_id))


async def readiness(s: AsyncSession, tenant_id: str, cluster: Cluster) -> bool:
    """Whether a cluster may be turned into a fix proposal, without building every other card."""
    since = utcnow() - timedelta(days=28)
    rows = (await s.execute(
        select(CallAnalysis.outcome, CallFeedback.rating)
        .join(Call, Call.id == CallAnalysis.call_id)
        .outerjoin(CallFeedback, CallFeedback.call_id == CallAnalysis.call_id)
        .where(CallAnalysis.tenant_id == tenant_id, CallAnalysis.cluster_id == cluster.id, Call.started_at >= since)
    )).all()
    escalations = sum(1 for outcome, _ in rows if outcome == "escalated")
    signals = sum(1 for outcome, rating in rows if outcome == "escalated" or rating == "down")
    return bool(impact(cluster, escalations, recent_signals=signals)["ready_for_fix"])
