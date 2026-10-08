"""Knowledge ingestion: text, files, URLs and OKF bundles -> docs + embedded chunks.

Spec: /architecture/knowledge.md
"""
from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.errors import ApiError
from voiceai.knowledge import okf
from voiceai.knowledge.chunking import chunk_markdown
from voiceai.core.embeddings import embed
from voiceai.knowledge.search import invalidate
from voiceai.core.tables import KnowledgeChunk, KnowledgeDoc

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
) -> KnowledgeDoc:
    if not content.strip():
        raise ApiError(422, "empty_document", "Document has no text content")
    doc = KnowledgeDoc(
        tenant_id=tenant_id, title=title.strip()[:300] or "Untitled", content=content,
        source_type=source_type, source_ref=source_ref[:500], meta=meta or {}, status=status,
    )
    session.add(doc)
    await session.flush()
    await rechunk(session, doc)
    return doc


async def rechunk(session: AsyncSession, doc: KnowledgeDoc) -> int:
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id))
    chunks = chunk_markdown(doc.content)
    texts = [f"{doc.title} — {c.heading}\n{c.content}" if c.heading else f"{doc.title}\n{c.content}" for c in chunks]
    vectors = await embed(texts, "passage") if texts else []
    for i, (c, v) in enumerate(zip(chunks, vectors)):
        session.add(KnowledgeChunk(
            tenant_id=doc.tenant_id, doc_id=doc.id, ordinal=i, heading=c.heading, content=c.content,
            embedding=[round(float(x), 6) for x in v],
        ))
    invalidate()
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


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in ("script", "style", "noscript", "nav", "footer"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div", "section"):
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "nav", "footer") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


async def text_from_url(url: str) -> tuple[str, str]:
    if not re.match(r"^https?://", url):
        raise ApiError(422, "invalid_url", "URL must start with http:// or https://")
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "VoiceAgentStudio/0.1"})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiError(422, "fetch_failed", f"Could not fetch URL: {exc}") from exc
    parser = _TextExtractor()
    parser.feed(resp.text)
    text = re.sub(r"\n\s*\n+", "\n\n", "".join(parser.parts)).strip()
    return (parser.title.strip() or url), text


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
