"""What other modules may use from fleet learning, and how they ask it for work.

Spec: /architecture/fleet-learning.md, /architecture/modular-structure.md

The dashboard reads cluster cards from here. Post-call analysis is *not* here: conversation asks
for that through `ports/postcall.py`, because learning names the conversation module to drive
simulated calls and the module graph must stay acyclic (MOD-01).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["top_clusters"]


async def top_clusters(s: AsyncSession, tenant_id: str, agent_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """The costliest open clusters, as the dashboard shows them."""
    from voiceai.modules.learning.service import cluster_cards

    return (await cluster_cards(s, tenant_id, agent_id))[:limit]
