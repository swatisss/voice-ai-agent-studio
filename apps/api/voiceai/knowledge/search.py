"""Cosine-similarity knowledge search with a no-answer threshold.

Spec: /architecture/knowledge.md (Search)
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.config import get_settings
from voiceai.models import KnowledgeChunk, KnowledgeDoc

NO_ANSWER = {"no_answer": True, "message": "No approved information found for this question."}
_cache: dict[tuple[str, tuple[str, ...], int], tuple[np.ndarray, list[dict[str, Any]]]] = {}
_version = 0


def invalidate() -> None:
    global _version
    _version += 1
    _cache.clear()


async def _matrix(session: AsyncSession, tenant_id: str, doc_ids: list[str]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    key = (tenant_id, tuple(sorted(set(doc_ids))), _version)
    if key in _cache:
        return _cache[key]
    rows = (
        await session.execute(
            select(KnowledgeChunk, KnowledgeDoc.title)
            .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeDoc.id.in_(key[1]),
                KnowledgeDoc.status != "archived",
            )
        )
    ).all()
    meta = [{"doc_id": c.doc_id, "title": t, "heading": c.heading, "content": c.content} for c, t in rows]
    mat = np.array([c.embedding for c, _ in rows], dtype=np.float32) if rows else np.zeros((0, 1), dtype=np.float32)
    _cache[key] = (mat, meta)
    return mat, meta


async def search(
    session: AsyncSession, tenant_id: str, doc_ids: list[str], query: str, top_k: int = 4
) -> dict[str, Any]:
    from voiceai.knowledge.embeddings import embed

    if not doc_ids or not query.strip():
        return dict(NO_ANSWER)
    mat, meta = await _matrix(session, tenant_id, doc_ids)
    if not meta:
        return dict(NO_ANSWER)
    q = (await embed([query], "query"))[0]
    scores = mat @ q
    order = np.argsort(-scores)
    threshold = get_settings().min_score
    results = []
    for i in order[: top_k * 2]:
        score = float(scores[i])
        if score < threshold:
            break
        m = meta[i]
        results.append({**m, "content": m["content"][:700], "score": round(score, 3)})
        if len(results) >= top_k:
            break
    return {"results": results} if results else dict(NO_ANSWER)
