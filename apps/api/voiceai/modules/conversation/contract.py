"""What other modules may use from conversation. Nothing else here is theirs.

Spec: /architecture/agent-runtime.md, /architecture/modular-structure.md

This module is upstream of everything that reacts to a call: fleet learning drives simulated calls
and reads transcripts, the hand-off console builds a packet from one, the voice pipeline runs the
brain. So all three name this contract, and this module names none of them back - what it genuinely
needs from them (post-call analysis, the hand-off desk, live voice control) it reaches through a
port instead, which is what keeps the module graph acyclic (MOD-01).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_owned
from voiceai.core.tables import Call, CallEvent

if TYPE_CHECKING:  # the type the voice pipeline drives
    from voiceai.modules.conversation.session import AgentSession as AgentSession
else:  # resolved on use so this file stays cheap to import
    def __getattr__(name: str):  # noqa: ANN202
        if name == "AgentSession":
            from voiceai.modules.conversation.session import AgentSession

            return AgentSession
        raise AttributeError(name)
from voiceai.modules.conversation.endings import IDLE_LINE, MAX_DURATION_LINE, REMINDER_LINE, is_farewell
from voiceai.modules.conversation.domain import transcript_lines
from voiceai.modules.conversation.serializers import call_summary as _summary

__all__ = [
    "IDLE_LINE", "MAX_DURATION_LINE", "REMINDER_LINE", "AgentSession", "call_events", "call_summary",
    "call_transcript", "get_call", "is_farewell", "open_session", "open_simulation", "transcript_lines",
]


async def get_call(s: AsyncSession, tenant_id: str, call_id: str) -> Call | None:
    """One tenant's call, or None when it is not theirs (MT-05)."""
    return await get_owned(s, Call, tenant_id, call_id)


async def call_events(s: AsyncSession, tenant_id: str, call_id: str) -> list[CallEvent]:
    """A call's events in order. Filtered by tenant in its own right, not via the parent."""
    return list((await s.scalars(
        select(CallEvent)
        .where(CallEvent.call_id == call_id, CallEvent.tenant_id == tenant_id)
        .order_by(CallEvent.seq)
    )).all())


async def call_transcript(s: AsyncSession, tenant_id: str, call_id: str) -> str:
    """The call as "Caller:" / "Agent:" / "Tool ..." lines, for a prompt or a packet."""
    return transcript_lines(await call_events(s, tenant_id, call_id))


def call_summary(call: Call, **extra: Any) -> dict[str, Any]:
    """The list-row view of a call, shared by the explorer, the console and the dashboard."""
    return _summary(call, **extra)


async def open_session(call_id: str, tenant_id: str, caller: Any | None = None):  # noqa: ANN201
    """The live session for a call, so the voice pipeline can drive the same brain the text
    channel uses (/architecture/agent-runtime.md: behaviour must not differ between channels)."""
    from voiceai.modules.conversation.session import AgentSession

    return await AgentSession.open(call_id, tenant_id, caller=caller)


async def open_simulation(
    *, tenant_id: str, agent_id: str, version_id: str, tenant_name: str, config: dict[str, Any]
):  # noqa: ANN201
    """Start an evaluation call against `config`, which may be a candidate that was never published.

    Fleet learning keeps the caller loop, the turn cap and the simulator prompt; creating the call
    and running the brain is this module's business (/architecture/evaluation.md).
    """
    from voiceai.core.db import sessionmaker
    from voiceai.modules.conversation.session import AgentSession

    async with sessionmaker()() as s:
        call = Call(tenant_id=tenant_id, agent_id=agent_id, agent_version_id=version_id,
                    channel="simulation", is_eval=True)
        s.add(call)
        await s.commit()
    return AgentSession(call=call, config=config, tenant_name=tenant_name)
