"""What other modules may use from the hand-off console.

Spec: /architecture/escalation.md, /architecture/modular-structure.md

The conversation module creates an escalation (the triggers live inside its turn loop and cannot
leave it) and needs the vocabulary to categorise one. Everything after that - the queue, the
packet, accept and resolve - is this module's and is reached only through its API.
"""
from __future__ import annotations

from voiceai.modules.handoff.domain import ESCALATION_CATEGORIES

__all__ = ["ESCALATION_CATEGORIES", "create_escalation", "escalation_summary"]


async def create_escalation(
    tenant_id: str, call_id: str, agent_id: str, category: str, detail: str,
    tools_used: list[dict] | None = None, verified_ref: str | None = None, is_eval: bool = False,
) -> str:
    """Open an escalation for a live call and start its groundwork packet. Returns its id."""
    from voiceai.modules.handoff.service import create

    return await create(tenant_id, call_id, agent_id, category, detail, tools_used or [], verified_ref, is_eval=is_eval)


def escalation_summary(escalation) -> dict:  # noqa: ANN001
    from voiceai.modules.handoff.service import summary

    return summary(escalation)
