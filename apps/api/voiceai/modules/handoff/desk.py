"""The hand-off desk: this module's implementation of ports/handoff.py.

Spec: /architecture/escalation.md
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.tables import Escalation
from voiceai.modules.handoff.service import create, summary


class InProcessHandoffDesk:
    async def open(
        self, tenant_id: str, call_id: str, agent_id: str, category: str, detail: str,
        tools_used: list[dict[str, Any]] | None = None, verified_ref: str | None = None,
        is_eval: bool = False,
    ) -> str:
        return await create(tenant_id, call_id, agent_id, category, detail, tools_used or [], verified_ref, is_eval=is_eval)

    async def for_call(self, s: AsyncSession, tenant_id: str, call_id: str) -> dict[str, Any] | None:
        esc = await s.scalar(
            select(Escalation).where(Escalation.call_id == call_id, Escalation.tenant_id == tenant_id)
        )
        return summary(esc) if esc else None
