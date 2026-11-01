"""Knowledge documents: list, ingest (text/url/upload/OKF zip), archive, search; website sources (CP-0031).

Spec: /api/rest-api.md (Tools, skills, knowledge), /architecture/knowledge.md
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.knowledge import fetch, ingest, okf, sources
from voiceai.knowledge.search import search
from voiceai.models import KnowledgeChunk, KnowledgeDoc, KnowledgeSource
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api/knowledge")


def doc_out(d: KnowledgeDoc, chunk_count: int | None = None) -> dict:
    out = {"id": d.id, "title": d.title, "source_type": d.source_type, "source_ref": d.source_ref, "status": d.status,
           "meta": d.meta, "source_id": d.source_id, "created_at": d.created_at.isoformat()}
    if chunk_count is not None:
        out["chunk_count"] = chunk_count
    return out


class TextBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)


class UrlBody(BaseModel):
    url: str


class SearchBody(BaseModel):
    query: str
    doc_ids: list[str] | None = None
    source_ids: list[str] | None = None


class SourceBody(BaseModel):
    start_url: str = Field(min_length=8, max_length=500)
    scope: Literal["page", "section"] = "section"
    max_pages: int = Field(default=25, ge=1, le=100)
    refresh: Literal["off", "daily", "weekly"] = "daily"
    title: str = Field(default="", max_length=300)


class SourceUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    max_pages: int | None = Field(default=None, ge=1, le=100)
    refresh: Literal["off", "daily", "weekly"] | None = None


def _iso(d) -> str | None:  # noqa: ANN001
    return d.isoformat() if d else None


def source_out(src: KnowledgeSource) -> dict:
    return {"id": src.id, "kind": src.kind, "title": src.title, "start_url": src.start_url, "scope": src.scope,
            "max_pages": src.max_pages, "refresh": src.refresh, "status": src.status, "page_count": src.page_count,
            "found_count": src.found_count, "last_synced_at": _iso(src.last_synced_at), "next_sync_at": _iso(src.next_sync_at),
            "last_run": src.last_run or {}, "error": src.error, "created_at": _iso(src.created_at)}


async def _source(s: AsyncSession, tenant_id: str, source_id: str) -> KnowledgeSource:
    src = await s.scalar(select(KnowledgeSource).where(KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == tenant_id))
    if not src or src.status == "archived":
        raise ApiError(404, "source_not_found", "Knowledge source not found")
    return src


@router.get("")
async def list_docs(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    counts = dict((await s.execute(
        select(KnowledgeChunk.doc_id, func.count()).where(KnowledgeChunk.tenant_id == tenant_id).group_by(KnowledgeChunk.doc_id)
    )).all())
    docs = (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.status != "archived")
                            .order_by(KnowledgeDoc.created_at))).all()
    return {"items": [doc_out(d, counts.get(d.id, 0)) for d in docs]}


# ------------------------------------------------------------------ website sources (declared before /{doc_id})
@router.get("/sources")
async def list_sources(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.status != "archived")
                            .order_by(KnowledgeSource.created_at))).all()
    return {"items": [source_out(r) for r in rows]}


@router.post("/sources", status_code=202)
async def create_source(body: SourceBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    url = body.start_url.strip()
    try:
        await fetch.check_address(url)
    except fetch.FetchError as exc:
        raise ApiError(422, exc.code, exc.detail) from exc
    src = KnowledgeSource(tenant_id=tenant_id, start_url=url, scope=body.scope, max_pages=body.max_pages,
                          refresh=body.refresh, title=body.title.strip() or url)
    s.add(src)
    await s.flush()
    await sources.queue_sync(s, src)
    await s.commit()
    return source_out(src)


@router.get("/sources/{source_id}")
async def get_source(source_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    src = await _source(s, tenant_id, source_id)
    docs = (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.source_id == src.id).order_by(KnowledgeDoc.created_at))).all()
    ids = [d.id for d in docs]
    stats = {doc_id: (n, digest) for doc_id, n, digest in (await s.execute(
        select(KnowledgeChunk.doc_id, func.count(), func.max(KnowledgeChunk.content_hash))
        .where(KnowledgeChunk.doc_id.in_(ids)).group_by(KnowledgeChunk.doc_id))).all()}
    pages = [{"doc_id": d.id, "url": d.source_ref, "title": d.title, "status": d.status,
              "chunk_count": stats.get(d.id, (0, None))[0], "content_hash": stats.get(d.id, (0, None))[1],
              "updated_at": (d.updated_at or d.created_at).isoformat()} for d in docs]
    return {**source_out(src), "pages": pages}


@router.put("/sources/{source_id}")
async def update_source(source_id: str, body: SourceUpdate, tenant_id: str = Depends(current_tenant),
                        s: AsyncSession = Depends(get_session)) -> dict:
    src = await _source(s, tenant_id, source_id)
    for field in ("title", "max_pages", "refresh"):
        value = getattr(body, field)
        if value is not None:
            setattr(src, field, value)
    if body.refresh is not None:
        base = src.last_synced_at
        src.next_sync_at = base + sources.REFRESH[src.refresh] if base and src.refresh in sources.REFRESH else None
    await s.commit()
    return source_out(src)


@router.post("/sources/{source_id}/sync", status_code=202)
async def sync_source(source_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    job = await sources.queue_sync(s, await _source(s, tenant_id, source_id))
    await s.commit()
    return {"job_id": job.id}


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    await sources.archive_source(s, await _source(s, tenant_id, source_id))
    await s.commit()
    return Response(status_code=204)


@router.get("/{doc_id}")
async def get_doc(doc_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    doc = await s.scalar(select(KnowledgeDoc).where(KnowledgeDoc.id == doc_id, KnowledgeDoc.tenant_id == tenant_id))
    if not doc:
        raise ApiError(404, "doc_not_found", "Document not found")
    chunks = (await s.scalars(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id).order_by(KnowledgeChunk.ordinal))).all()
    return {**doc_out(doc, len(chunks)), "content": doc.content,
            "chunks": [{"ordinal": c.ordinal, "heading": c.heading, "content": c.content} for c in chunks]}


@router.post("/text")
async def add_text(body: TextBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    doc = await ingest.create_doc(s, tenant_id, body.title, body.content, "text")
    await s.commit()
    return doc_out(doc)


@router.post("/url")
async def add_url(body: UrlBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    title, content = await ingest.text_from_url(body.url)
    doc = await ingest.create_doc(s, tenant_id, title, content, "url", body.url)
    await s.commit()
    return doc_out(doc)


@router.post("/upload")
async def upload(file: UploadFile = File(...), tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    data = await file.read()
    name = file.filename or "upload"
    if name.lower().endswith(".zip"):
        concepts = okf.read_zip(data)
        if not concepts:
            raise ApiError(422, "empty_bundle", "No OKF concepts (Markdown with frontmatter `type`) found in the zip")
        docs = await ingest.import_okf(s, tenant_id, concepts, name)
    else:
        title, content = ingest.text_from_file(name, data)
        docs = [await ingest.create_doc(s, tenant_id, title, content, "file", name)]
    await s.commit()
    return {"items": [doc_out(d) for d in docs]}


@router.delete("/{doc_id}", status_code=204)
async def archive(doc_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    await ingest.archive_doc(s, tenant_id, doc_id)
    await s.commit()
    return Response(status_code=204)


@router.post("/search")
async def search_docs(body: SearchBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    doc_ids = body.doc_ids
    if doc_ids is None:
        doc_ids = list((await s.scalars(select(KnowledgeDoc.id).where(KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.status == "active"))).all())
    doc_ids = [*doc_ids, *await sources.page_ids(s, tenant_id, body.source_ids or [])]
    return await search(s, tenant_id, doc_ids, body.query)
