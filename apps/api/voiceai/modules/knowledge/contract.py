"""What other modules may use from knowledge.

Spec: /architecture/knowledge.md, /architecture/modular-structure.md
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_owned
from voiceai.core.tables import KnowledgeDoc

__all__ = ["activate_doc", "archive_draft_doc", "draft_article", "search_knowledge"]


async def search_knowledge(s: AsyncSession, tenant_id: str, doc_ids: list[str], query: str) -> dict[str, Any]:
    from voiceai.modules.knowledge.search import search

    return await search(s, tenant_id, doc_ids, query)


async def draft_article(
    s: AsyncSession, tenant_id: str, title: str, content: str, source_ref: str = "",
    meta: dict[str, Any] | None = None,
) -> str:
    """Create a draft article and return its id.

    Fleet learning proposes an article this way rather than writing this module's tables, and the
    provenance it passes (which cluster asked for it) is kept with the document.
    """
    from voiceai.modules.knowledge.service import create_doc

    doc = await create_doc(s, tenant_id, title, content, "proposal", source_ref, meta, status="draft")
    return doc.id


async def activate_doc(s: AsyncSession, tenant_id: str, doc_id: str) -> None:
    """Publish a draft article. Called when a fix proposal is approved."""
    doc = await get_owned(s, KnowledgeDoc, tenant_id, doc_id)
    if doc is not None:
        doc.status = "active"


async def archive_draft_doc(s: AsyncSession, tenant_id: str, doc_id: str) -> None:
    """Retire a draft article. Called when a fix proposal is rejected."""
    doc = await get_owned(s, KnowledgeDoc, tenant_id, doc_id)
    if doc is not None:
        doc.status = "archived"
