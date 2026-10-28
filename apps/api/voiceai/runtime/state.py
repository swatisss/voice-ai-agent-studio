"""Per-call state tracked by the runtime.

Spec: /architecture/agent-runtime.md (Call state)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallState:
    turns: int = 0
    verified: bool = False
    verified_member_ref: str | None = None
    verification_level: str = "unknown"  # unknown | identified | attested | verified (/architecture/caller-verification.md)
    identified_member_ref: str | None = None
    identified_first_name: str | None = None
    verification_attempts: int = 0
    memory_used: list[str] = field(default_factory=list)  # member memory loaded at verification (/architecture/agent-memory.md)
    no_answer_streak: int = 0
    tool_error_streak: int = 0
    no_answer_queries: list[str] = field(default_factory=list)
    tools_used: list[dict[str, Any]] = field(default_factory=list)
    escalated: bool = False
    escalation_id: str | None = None
    end_requested: bool = False
    ended: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latencies_ms: list[int] = field(default_factory=list)
