"""Knowledge ingestion: text, files, URLs and OKF bundles -> docs + embedded chunks.

Spec: /architecture/knowledge.md
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.errors import ApiError
from voiceai.knowledge import fetch, html, okf
from voiceai.knowledge.chunking import chunk_markdown
from voiceai.knowledge.embeddings import embed
from voiceai.knowledge.search import invalidate
from voiceai.models import KnowledgeChunk, KnowledgeDoc

MAX_UPLOAD = 5 * 1024 * 1024


async def create_doc(
    session: AsyncSession,
    tenant_id: str,
    title: str,
    content: str,
    source_type: str,
    source_ref: str = "",
    meta: dict[str, Any] | None = None,
    status: str = "active",
    source_id: str | None = None,
) -> KnowledgeDoc:
    if not content.strip():
        raise ApiError(422, "empty_document", "Document has no text content")
    doc = KnowledgeDoc(
        tenant_id=tenant_id, title=title.strip()[:300] or "Untitled", content=content,
        source_type=source_type, source_ref=source_ref[:500], meta=meta or {}, status=status, source_id=source_id,
    )
    session.add(doc)
    await session.flush()
    await rechunk(session, doc)
    return doc


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def rechunk(session: AsyncSession, doc: KnowledgeDoc) -> int:
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id))
    chunks = chunk_markdown(doc.content)
    digest = content_hash(doc.content)
    texts = [f"{doc.title} — {c.heading}\n{c.content}" if c.heading else f"{doc.title}\n{c.content}" for c in chunks]
    vectors = await embed(texts, "passage") if texts else []
    for i, (c, v) in enumerate(zip(chunks, vectors)):
        session.add(KnowledgeChunk(
            tenant_id=doc.tenant_id, doc_id=doc.id, ordinal=i, heading=c.heading, content=c.content,
            embedding=[round(float(x), 6) for x in v], content_hash=digest,
        ))
    invalidate()
    from voiceai.routing import catalog

    await catalog.enqueue_for_doc(session, doc.tenant_id, doc.id)  # CAT-03: profiles list the agent's knowledge
    return len(chunks)


def text_from_file(filename: str, data: bytes) -> tuple[str, str]:
    if len(data) > MAX_UPLOAD:
        raise ApiError(422, "file_too_large", "Files must be 5 MB or smaller")
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem.replace("-", " ").replace("_", " ").strip().capitalize()
    if suffix in (".md", ".txt"):
        text = data.decode("utf-8", errors="replace")
        meta, body = okf.split_frontmatter(text)
        title = str((meta or {}).get("title") or stem)
        return title, body
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        return stem, text
    raise ApiError(422, "unsupported_file", "Upload .md, .txt, .pdf or a .zip OKF bundle")


async def text_from_url(url: str) -> tuple[str, str]:
    """One page through the safe fetcher, as Markdown (/architecture/knowledge.md, Sources `url`)."""
    try:
        page = await fetch.fetch(url)
    except fetch.FetchError as exc:
        raise ApiError(422, exc.code if exc.code != "too_large" else "unsupported_content", exc.detail) from exc
    converted = html.to_markdown(page.text, page.url) if "html" in page.content_type else html.Page(url, page.text.strip())
    return converted.title, converted.markdown


async def import_okf(session: AsyncSession, tenant_id: str, concepts: list[okf.OkfConcept], source_ref: str) -> list[KnowledgeDoc]:
    docs = []
    for c in concepts:
        docs.append(await create_doc(session, tenant_id, c.title, c.content, "okf", f"{source_ref}:{c.path}", c.meta))
    return docs


async def archive_doc(session: AsyncSession, tenant_id: str, doc_id: str) -> None:
    doc = await session.scalar(select(KnowledgeDoc).where(KnowledgeDoc.id == doc_id, KnowledgeDoc.tenant_id == tenant_id))
    if not doc:
        raise ApiError(404, "doc_not_found", "Document not found")
    doc.status = "archived"
    invalidate()
    from voiceai.routing import catalog

    await catalog.enqueue_for_doc(session, tenant_id, doc_id)  # CAT-03
