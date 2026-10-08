"""Port: asking for a finished call to be analysed.

Spec: /architecture/fleet-learning.md, /architecture/jobs-and-events.md

This is a **port, not a contract on fleet learning**, and the reason is structural: learning
already names the conversation module to drive simulated calls, so conversation naming learning
back would make the module graph cyclic (MOD-01). Conversation states that something happened;
who reacts, under what job kind, with what dedupe key, is the implementer's business.

It MUST NOT be replaced by an event-bus publish: the bus drops events under load, which is right
for a live feed and wrong for work that must happen.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

Trigger = Literal["call_ended", "human_resolved", "caller_feedback"]


@runtime_checkable
class PostCallAnalysis(Protocol):
    async def request(self, s: AsyncSession, tenant_id: str, call_id: str, trigger: Trigger) -> None:
        """Ask for this call to be analysed. Idempotent per (call_id, trigger). The caller commits,
        so the request is part of the same transaction as whatever caused it."""
        ...
