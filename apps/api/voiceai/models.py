"""ORM models - the tables of the data model.

Spec: /data/data-model.md, /architecture/call-scoring.md, /architecture/self-learning.md, /api/public-api.md, /architecture/webhooks.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from voiceai.db import Base, UTCDateTime, new_id, utcnow


def _id() -> Mapped[str]:
    return mapped_column(String(32), primary_key=True, default=new_id)


def _tenant() -> Mapped[str]:
    return mapped_column(String(64), ForeignKey("tenants.id"), index=True, nullable=False)


def _created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = _created()


class TenantSettings(Base):
    """Per-tenant pipeline allowlist and key fallback; no row means the defaults (/architecture/tenant-settings.md)."""

    __tablename__ = "tenant_settings"
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), primary_key=True)
    allowed_pipelines: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["cascade"])
    openai_platform_fallback: Mapped[bool] = mapped_column(Boolean, default=True)
    front_desk: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # /architecture/supervisor-routing.md
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class TenantCredential(Base):
    """A tenant's own provider key, Fernet-encrypted; the plain key is never stored (/architecture/tenant-settings.md)."""

    __tablename__ = "tenant_credentials"
    __table_args__ = (UniqueConstraint("tenant_id", "provider"),)
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    provider: Mapped[str] = mapped_column(String(32))
    ciphertext: Mapped[str] = mapped_column(Text)
    last4: Mapped[str] = mapped_column(String(4))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    draft_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    published_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Persona(Base):
    __tablename__ = "personas"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    name: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200), default="")
    voice: Mapped[str] = mapped_column(String(64), default="aura-2-thalia-en")
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    greeting: Mapped[str] = mapped_column(String(300))
    disclosure: Mapped[str] = mapped_column(String(300))
    opening: Mapped[str] = mapped_column(String(400), default="")
    style: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    change_note: Mapped[str] = mapped_column(Text, default="")
    source_proposal_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = _created()


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(8), default="GET")
    url: Mapped[str] = mapped_column(String(500))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_s: Mapped[int] = mapped_column(Integer, default=8)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    required_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    escalate_when: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class KnowledgeSource(Base):
    """A website that turns into page docs and stays in sync (/architecture/knowledge.md, Website sources; CP-0031)."""

    __tablename__ = "knowledge_sources"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    kind: Mapped[str] = mapped_column(String(16), default="website")
    title: Mapped[str] = mapped_column(String(300), default="")
    start_url: Mapped[str] = mapped_column(String(500))
    scope: Mapped[str] = mapped_column(String(16), default="section")  # page | section
    max_pages: Mapped[int] = mapped_column(Integer, default=25)
    refresh: Mapped[str] = mapped_column(String(16), default="daily")  # off | daily | weekly
    status: Mapped[str] = mapped_column(String(16), default="indexing")  # indexing | ready | partial | failed | archived
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_run: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    title: Mapped[str] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(16))
    source_ref: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _created()
    source_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("knowledge_sources.id"), nullable=True, index=True)  # DM-12
    miss_count: Mapped[int] = mapped_column(Integer, default=0)  # consecutive syncs that found the page gone (KN-14)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=True)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    doc_id: Mapped[str] = mapped_column(String(32), ForeignKey("knowledge_docs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256 of the doc content it was cut from (DM-12)


class Call(Base):
    __tablename__ = "calls"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_version_id: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(16), default="inbound", index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    caller_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_p50_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_eval: Mapped[bool] = mapped_column(Boolean, default=False)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # a conversation's segment
    segment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    routed_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CallEvent(Base):
    __tablename__ = "call_events"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    call_id: Mapped[str] = mapped_column(String(32), ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Escalation(Base):
    __tablename__ = "escalations"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    call_id: Mapped[str] = mapped_column(String(32), ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    reason_category: Mapped[str] = mapped_column(String(32))
    reason_detail: Mapped[str] = mapped_column(Text, default="")
    packet: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    packet_status: Mapped[str] = mapped_column(String(16), default="pending")
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class CallFeedback(Base):
    """The caller's thumbs up or down after a call (one row per call, replaced on a new answer). Spec: /architecture/call-ending-and-feedback.md"""
    __tablename__ = "call_feedback"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    call_id: Mapped[str] = mapped_column(String(32), ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    rating: Mapped[str] = mapped_column(String(8))  # up | down
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class CallAnalysis(Base):
    __tablename__ = "call_analyses"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    call_id: Mapped[str] = mapped_column(String(32), ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(16))
    intent: Mapped[str] = mapped_column(String(80), default="")
    root_cause: Mapped[str] = mapped_column(String(32), default="none")
    fixable: Mapped[bool] = mapped_column(Boolean, default=False)
    gap_summary: Mapped[str] = mapped_column(Text, default="")
    caller_goal: Mapped[str] = mapped_column(Text, default="")
    resolution_summary: Mapped[str] = mapped_column(Text, default="")
    sentiment_start: Mapped[str] = mapped_column(String(16), default="neutral")
    sentiment_end: Mapped[str] = mapped_column(String(16), default="neutral")
    signals: Mapped[list[str]] = mapped_column(JSON, default=list)  # quality signals it was re-analysed with (SL-02)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(8), default="llm")
    created_at: Mapped[datetime] = _created()


class Cluster(Base):
    __tablename__ = "clusters"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    root_cause: Mapped[str] = mapped_column(String(32))
    fixable: Mapped[bool] = mapped_column(Boolean, default=False)
    centroid: Mapped[list[float]] = mapped_column(JSON)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    escalation_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # SL-05
    human_answer: Mapped[str | None] = mapped_column(Text, nullable=True)  # a reviewer's answer (answer_needed, CP-0032)
    human_answer_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # the fix did not hold (SL-15)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class CallScorecard(Base):
    """Measures and check verdicts of one scored real call (/architecture/call-scoring.md)."""

    __tablename__ = "call_scorecards"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    call_id: Mapped[str] = mapped_column(String(32), ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_version_id: Mapped[str] = mapped_column(String(32), index=True)
    measures: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    hard_fail: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    judged: Mapped[bool] = mapped_column(Boolean, default=False)
    judge_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(8), default="llm")  # llm | seed
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class CheckReview(Base):
    """A reviewer's own verdict on one judge check of a scorecard (/architecture/call-scoring.md)."""

    __tablename__ = "check_reviews"
    __table_args__ = (UniqueConstraint("scorecard_id", "check_key"),)
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    scorecard_id: Mapped[str] = mapped_column(String(32), ForeignKey("call_scorecards.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    check_key: Mapped[str] = mapped_column(String(80))
    judge_verdict: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str] = mapped_column(String(8))  # pass | fail | n/a
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class FixProposal(Base):
    __tablename__ = "fix_proposals"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    cluster_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    origin: Mapped[str] = mapped_column(String(16), default="manual")  # manual | nightly
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    draft_doc_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    latest_eval_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resulting_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)  # null for routing runs
    kind: Mapped[str] = mapped_column(String(16), default="proposal")  # proposal | suite (/architecture/test-suites.md)
    proposal_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    baseline_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target: Mapped[str | None] = mapped_column(String(16), nullable=True)  # published | draft | version
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    repeats: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(16), default="proposal")  # manual | builder | publish | proposal
    scenario_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="running")
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class EvalResult(Base):
    __tablename__ = "eval_results"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    eval_run_id: Mapped[str] = mapped_column(String(32), ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    case_key: Mapped[str] = mapped_column(String(120))
    case_type: Mapped[str] = mapped_column(String(16))
    arm: Mapped[str] = mapped_column(String(16))
    scenario_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    repeat: Mapped[int] = mapped_column(Integer, default=1)
    scenario: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected: Mapped[str] = mapped_column(String(16))
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    failures: Mapped[list[str]] = mapped_column(JSON, default=list)
    judge: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class EvalScenario(Base):
    __tablename__ = "eval_scenarios"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    caller_goal: Mapped[str] = mapped_column(Text)
    caller_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    persona: Mapped[str] = mapped_column(String(16), default="calm")  # calm | confused | impatient | adversarial
    expected: Mapped[str] = mapped_column(String(16), default="resolved")
    required_tools: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    forbidden_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    memory: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class UseCase(Base):
    __tablename__ = "use_cases"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    sample_utterances: Mapped[list[str]] = mapped_column(JSON, default=list)
    demo_callers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=True)


class PhoneNumber(Base):
    """An inbound phone number routed to one agent (/architecture/telephony.md)."""

    __tablename__ = "phone_numbers"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    e164: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # unique across all tenants
    target: Mapped[str] = mapped_column(String(16), default="agent")  # agent | front_desk (TEL-12)
    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = _created()


class MemberMemory(Base):
    """One episode or fact an agent remembers about a verified member (/architecture/agent-memory.md)."""

    __tablename__ = "member_memories"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    member_ref: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # episode | fact
    category: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | retired
    valid_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    invalid_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    source_call_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class MemoryEvent(Base):
    """Append-only history of member memory; content is emptied by expiry and erasure."""

    __tablename__ = "memory_events"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    member_ref: Mapped[str] = mapped_column(String(64), index=True)
    memory_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(16))  # added | superseded | confirmed | restored | expired | erased
    actor: Mapped[str] = mapped_column(String(16))   # agent | studio | system
    call_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class LearningRun(Base):
    """One nightly (or manual) self-learning run of a tenant (/architecture/self-learning.md)."""

    __tablename__ = "learning_runs"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    trigger: Mapped[str] = mapped_column(String(16), default="nightly")  # nightly | manual
    status: Mapped[str] = mapped_column(String(16), default="running")
    since: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class LearningAction(Base):
    """One finding of evaluation or learning with one next step for a person (/architecture/learning-actions.md)."""

    __tablename__ = "learning_actions"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # fix_not_holding | answer_needed | check_failing | drift | scenario_failing
    key: Mapped[str] = mapped_column(String(200), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")  # high | medium
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | done | dismissed | resolved
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    impact: Mapped[float] = mapped_column(Float, default=0.0)
    closed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    suppressed_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # done or dismissed: not reopened before
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ApiKey(Base):
    """A tenant's machine credential for /v1; only its SHA-256 hash is stored (/api/public-api.md)."""

    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    name: Mapped[str] = mapped_column(String(60))
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(16))  # member | staff
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=120)
    max_concurrent_voice: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Conversation(Base):
    """One caller connection that may pass through several agents; each agent's part is a call (segment)."""

    __tablename__ = "conversations"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    source: Mapped[str] = mapped_column(String(16))  # api | playground | phone
    api_key_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(8))  # text | voice
    transport: Mapped[str] = mapped_column(String(16))  # text | websocket | media-stream | webrtc | twilio | browser
    scope: Mapped[str] = mapped_column(String(16))  # member | staff
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active | escalated | ended
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    current_call_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transfer_count: Mapped[int] = mapped_column(Integer, default=0)
    clarifications: Mapped[int] = mapped_column(Integer, default=0)
    routing: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class WebhookEndpoint(Base):
    """A tenant's webhook URL; the secret is encrypted because signing needs it (/architecture/webhooks.md)."""

    __tablename__ = "webhook_endpoints"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    include_transcript: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    previous_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class WebhookDelivery(Base):
    """One event for one endpoint, with its attempts (/architecture/webhooks.md, Delivery)."""

    __tablename__ = "webhook_deliveries"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    endpoint_id: Mapped[str] = mapped_column(String(32), index=True)
    event_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str] = mapped_column(String(40))
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | delivered | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = _created()
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class CapabilityProfile(Base):
    """What the supervisor knows about one routable agent (/architecture/capability-catalog.md)."""

    __tablename__ = "capability_profiles"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), unique=True)
    agent_version_id: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(16))
    card: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="ready")  # ready | indexing | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    built_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CapabilityEntry(Base):
    """One embedded, searchable text of a capability profile."""

    __tablename__ = "capability_entries"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    profile_id: Mapped[str] = mapped_column(String(32), ForeignKey("capability_profiles.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # description | use_case | utterance | generated | tool
    ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON)


class RoutingCase(Base):
    """A routing-suite case: an utterance and the agent that should get it."""

    __tablename__ = "routing_cases"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    utterance: Mapped[str] = mapped_column(String(300))
    expected_agent_id: Mapped[str] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))  # generated | manual
    use_case_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
