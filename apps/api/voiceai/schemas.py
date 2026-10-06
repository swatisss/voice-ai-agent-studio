"""Pydantic schemas for agent config, tools, skills and LLM structured outputs.

Spec: /data/agent-config.md, /architecture/escalation.md, /architecture/fleet-learning.md, /architecture/evaluation.md
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

BUILTIN_TOOLS = {"search_knowledge", "escalate_to_human", "end_call"}
ESCALATION_CATEGORIES = (
    "caller_requested", "policy_required", "safety", "knowledge_gap", "capability_gap", "tool_failure", "frustration", "other",
)
ROOT_CAUSES = (
    "none", "missing_knowledge", "missing_skill", "tool_error", "policy_required", "safety",
    "caller_requested", "asr_error", "agent_error", "other",
)
FIXABLE = {"missing_knowledge", "missing_skill", "agent_error"}
SENTIMENTS = ("positive", "neutral", "frustrated", "angry", "distressed")
DISPOSITIONS = ("resolved_by_human", "appeal_filed", "callback_scheduled", "transferred_department", "no_action_needed", "other")

ShortText = Field(default="", max_length=300)


# ------------------------------------------------------------------ agent config
class Persona(BaseModel):
    name: str = Field(default="Ava", min_length=1, max_length=40)
    voice: str = "aura-2-thalia-en"
    greeting: str = Field(default="Thanks for calling, this is Ava.", min_length=1, max_length=300)
    disclosure: str = Field(default="I'm a virtual assistant, and this call may be recorded for quality.", min_length=1, max_length=300)
    style: str = Field(default="Warm, calm and concise. One question at a time.", max_length=500)


class Policy(BaseModel):
    rules: list[str] = Field(default_factory=list, max_length=30)
    escalate_when: list[str] = Field(default_factory=list, max_length=30)
    never: list[str] = Field(default_factory=list, max_length=30)
    max_turns: int = Field(default=16, ge=4, le=40)
    handoff_message: str = Field(
        default="I'm connecting you with a specialist who will have all the details, so you won't need to repeat yourself.",
        max_length=300,
    )
    holding_message: str = Field(default="A specialist will be with you shortly. Thanks for your patience.", max_length=300)
    safety_screen: bool = True
    voice_filler: bool = True

    @field_validator("rules", "escalate_when", "never")
    @classmethod
    def _short_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 300:
                raise ValueError("list items must be 300 characters or fewer")
        return [i.strip() for i in v if i.strip()]


class ModelChoice(BaseModel):
    realtime: str | None = None


class AgentConfig(BaseModel):
    persona: Persona = Field(default_factory=Persona)
    policy: Policy = Field(default_factory=Policy)
    tool_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    knowledge_doc_ids: list[str] = Field(default_factory=list)
    models: ModelChoice = Field(default_factory=ModelChoice)


class ToolDef(BaseModel):
    name: str
    description: str = Field(default="", max_length=1000)
    method: Literal["GET", "POST"] = "GET"
    url: str = Field(min_length=1, max_length=500)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    requires_verification: bool = False
    is_verification: bool = False
    timeout_s: int = Field(default=8, ge=1, le=30)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", v):
            raise ValueError("name must be snake_case, 3-41 characters, starting with a letter")
        if v in BUILTIN_TOOLS:
            raise ValueError(f"'{v}' is a built-in tool name")
        return v

    @field_validator("parameters")
    @classmethod
    def _params(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v.get("type") != "object":
            raise ValueError("parameters must be a JSON Schema object with type: object")
        v.setdefault("properties", {})
        return v


class SkillDef(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=4000)
    required_tools: list[str] = Field(default_factory=list)
    escalate_when: str = Field(default="", max_length=500)


# ------------------------------------------------------------------ LLM outputs
class Sentiment(BaseModel):
    start: str = "neutral"
    end: str = "neutral"
    trend: str = "stable"


class EscalationReason(BaseModel):
    category: str
    detail: str = ""


class Packet(BaseModel):
    summary: str
    intent: str = "unknown"
    entities: dict[str, Any] = Field(default_factory=dict)
    already_tried: list[str] = Field(default_factory=list)
    escalation_reason: EscalationReason
    sentiment: Sentiment = Field(default_factory=Sentiment)
    suggested_next_action: str = ""
    caller_verified: bool = False


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
