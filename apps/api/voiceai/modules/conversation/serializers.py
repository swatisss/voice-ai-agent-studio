"""The views of a call the API returns: list row, analysis, feedback.

Spec: /api/rest-api.md (Calls), /architecture/modular-structure.md

These are shared: the call explorer, the hand-off console and the dashboard all render a call the
same way. They used to live in the calls router, which is why the console imported another route
module to reuse one of them.
"""
from __future__ import annotations

from typing import Any

from voiceai.core.tables import Call, CallAnalysis, CallFeedback


def feedback_out(f: CallFeedback | None) -> dict[str, Any] | None:
    if f is None:
        return None
    return {"rating": f.rating, "comment": f.comment or "", "at": (f.updated_at or f.created_at).isoformat()}


def call_summary(c: Call, analysis: CallAnalysis | None = None, version: int | None = None, feedback: str | None = None) -> dict[str, Any]:
    return {
        "feedback": feedback,
        "id": c.id, "agent_id": c.agent_id, "agent_version_id": c.agent_version_id, "agent_version": version,
        "channel": c.channel, "direction": c.direction, "status": c.status, "outcome": c.outcome, "caller_ref": c.caller_ref,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "ended_at": c.ended_at.isoformat() if c.ended_at else None, "end_reason": c.end_reason,
        "turn_count": c.turn_count, "tokens_in": c.tokens_in, "tokens_out": c.tokens_out,
        "llm_cost_usd": c.llm_cost_usd, "latency_p50_ms": c.latency_p50_ms, "is_seed": c.is_seed,
        "intent": analysis.intent if analysis else None, "root_cause": analysis.root_cause if analysis else None,
    }


def analysis_out(a: CallAnalysis | None) -> dict[str, Any] | None:
    if not a:
        return None
    return {k: getattr(a, k) for k in ("outcome", "intent", "root_cause", "fixable", "gap_summary", "caller_goal",
                                        "resolution_summary", "sentiment_start", "sentiment_end", "cluster_id", "source")}
