"""ORM models - the 17 tables of the data model.

Spec: /data/data-model.md
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


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    doc_id: Mapped[str] = mapped_column(String(32), ForeignKey("knowledge_docs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON)


class Call(Base):
    __tablename__ = "calls"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_version_id: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16))
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
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class FixProposal(Base):
    __tablename__ = "fix_proposals"
    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant()
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    cluster_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(24))
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
    agent_id: Mapped[str] = mapped_column(String(32), index=True)
    proposal_id: Mapped[str] = mapped_column(String(32), index=True)
    baseline_version_id: Mapped[str] = mapped_column(String(32))
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
    call_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected: Mapped[str] = mapped_column(String(16))
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
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
    expected: Mapped[str] = mapped_column(String(16), default="resolved")
    created_at: Mapped[datetime] = _created()


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
