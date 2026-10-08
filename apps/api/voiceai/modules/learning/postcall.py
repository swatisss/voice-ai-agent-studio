"""This module's implementation of ports/postcall.py.

Spec: /architecture/fleet-learning.md, /architecture/jobs-and-events.md

The job kind and its dedupe convention live here and nowhere else. They used to be spelled out at
three call sites in two other modules, each having to remember the suffix that makes a re-analysis
distinct from the first one.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core import jobs
from voiceai.ports.postcall import Trigger

KIND = "analyze_call"
# one analysis per call per reason: the first pass, the human's resolution, the caller's rating
SUFFIX: dict[str, str] = {"call_ended": "", "human_resolved": ":2", "caller_feedback": ":feedback"}


class LearningPostCallAnalysis:
    async def request(self, s: AsyncSession, tenant_id: str, call_id: str, trigger: Trigger) -> None:
        await jobs.enqueue(s, tenant_id, KIND, {"call_id": call_id}, dedupe_key=f"{KIND}:{call_id}{SUFFIX[trigger]}")
