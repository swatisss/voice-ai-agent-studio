"""Port: handing a call to a human.

Spec: /architecture/escalation.md, /architecture/modular-structure.md

The triggers that decide a call needs a person - the safety screen, repeated no-answers, repeated
tool failures, the turn cap - run inside the turn loop and cannot leave it. What happens next (a
queue, a groundwork packet, somebody accepting it) is the console's business, on its own clock.

This is a port rather than a contract on the console module because the console reads calls and
transcripts, so a contract in this direction would make the module graph cyclic (MOD-01). The
conversation module announces; whoever runs the desk reacts.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

# The vocabulary of the `category` argument below. It lives with the port because the conversation
# module has to name a category when it raises a hand-off, and it may not name the console module.
HANDOFF_CATEGORIES = (
    "caller_requested", "policy_required", "safety", "knowledge_gap", "capability_gap", "tool_failure",
    "frustration", "other",
)


@runtime_checkable
class HandoffDesk(Protocol):
    async def open(
        self, tenant_id: str, call_id: str, agent_id: str, category: str, detail: str,
        tools_used: list[dict[str, Any]] | None = None, verified_ref: str | None = None,
        is_eval: bool = False,
    ) -> str:
        """Open a hand-off for a live call and return its id. Also starts its groundwork packet."""
        ...

    async def for_call(self, s: AsyncSession, tenant_id: str, call_id: str) -> dict[str, Any] | None:
        """The hand-off raised on this call, as a summary, or None."""
        ...
