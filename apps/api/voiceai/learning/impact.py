"""Cluster impact, readiness and labels.

Spec: /architecture/fleet-learning.md (3. Impact and readiness)
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from voiceai.core.config import get_settings
from voiceai.core.db import utcnow
from voiceai.core.tables import Cluster

CORRECT = {"policy_required", "safety", "caller_requested"}


def impact(c: Cluster, recent_escalations: int | None = None, now=None, recent_signals: int | None = None) -> dict[str, Any]:  # noqa: ANN001
    """recent_escalations = escalations in the last 28 days (defaults to total if all are recent).

    recent_signals = escalations plus thumbs-down calls in that window; it decides readiness (FB-04). Defaults to
    the escalation count, so callers that do not know about feedback behave as before.
    """
    s = get_settings()
    now = now or utcnow()
    recent = c.escalation_count if recent_escalations is None else recent_escalations
    if recent_escalations is None and c.last_seen_at and c.last_seen_at < now - timedelta(days=28):
        recent = 0
    signals = recent if recent_signals is None else recent_signals
    weekly = recent / 4
    ready = bool(c.fixable and signals >= s.fl_min_cluster_size and c.status == "open")
    if c.status == "fixed":
        label = "fixed"
    elif c.status == "fix_proposed":
        label = "fix_proposed"
    elif c.status == "ignored":
        label = "ignored"
    elif not c.fixable:
        label = "correct_escalation" if c.root_cause in CORRECT else "investigate"
    elif ready:
        label = "ready_for_fix"
    else:
        label = "watching"
    return {
        "weekly_escalations": round(weekly, 2),
        "est_weekly_cost_usd": round(weekly * (s.human_cost_per_call - s.ai_cost_per_call), 2),
        "ready_for_fix": ready,
        "label": label,
        "min_cluster_size": s.fl_min_cluster_size,
    }
