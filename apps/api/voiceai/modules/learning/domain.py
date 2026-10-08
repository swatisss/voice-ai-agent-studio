"""Fleet learning's own rules and shapes: cluster impact and readiness, and the structured
outputs the models must return.

Spec: /architecture/fleet-learning.md, /architecture/evaluation.md, /prompts/call-analysis.md,
      /prompts/fix-draft.md, /prompts/eval-judge.md
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from voiceai.core.config import get_settings
from voiceai.core.db import utcnow
from voiceai.core.tables import Cluster

# FixDraft embeds a skill definition, which agent configuration owns
from voiceai.modules.agentcfg.contract import SkillDef

# escalations that were the right call, so they do not count against the agent
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


# ------------------------------------------------- structured LLM outputs
ROOT_CAUSES = (
    "none", "missing_knowledge", "missing_skill", "tool_error", "policy_required", "safety",
    "caller_requested", "asr_error", "agent_error", "other",
)
FIXABLE = {"missing_knowledge", "missing_skill", "agent_error"}


class AnalysisOut(BaseModel):
    outcome: Literal["resolved", "escalated", "abandoned"]
    intent: str = ""
    root_cause: str = "none"
    gap_summary: str = ""
    caller_goal: str = ""
    resolution_summary: str = ""
    sentiment_start: str = "neutral"
    sentiment_end: str = "neutral"

    @field_validator("root_cause")
    @classmethod
    def _rc(cls, v: str) -> str:
        return v if v in ROOT_CAUSES else "other"


class ClusterName(BaseModel):
    name: str
    description: str = ""


class ArticleDraft(BaseModel):
    title: str
    content_markdown: str


class FixDraft(BaseModel):
    kind: Literal["knowledge_article", "skill", "policy_rule"]
    title: str
    rationale: str = ""
    article: ArticleDraft | None = None
    skill: SkillDef | None = None
    tool: dict[str, Any] | None = None
    existing_tool_name: str | None = None
    rule: str | None = None


class JudgeOut(BaseModel):
    outcome: Literal["resolved", "escalated", "abandoned"]
    goal_met: bool = False
    grounded: bool = True
    policy_violations: list[str] = Field(default_factory=list)
    notes: str = ""
