"""Knowledge documents: list, ingest (text/url/upload/OKF zip), archive, search.

Spec: /api/rest-api.md (Tools, skills, knowledge), /architecture/knowledge.md
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.knowledge import ingest, okf
from voiceai.knowledge.search import search
from voiceai.models import KnowledgeChunk, KnowledgeDoc
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api/knowledge")


def doc_out(d: KnowledgeDoc, chunk_count: int | None = None) -> dict:
    out = {"id": d.id, "title": d.title, "source_type": d.source_type, "source_ref": d.source_ref, "status": d.status,
           "meta": d.meta, "created_at": d.created_at.isoformat()}
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


@router.get("")
async def list_docs(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    counts = dict((await s.execute(
        select(KnowledgeChunk.doc_id, func.count()).where(KnowledgeChunk.tenant_id == tenant_id).group_by(KnowledgeChunk.doc_id)
    )).all())
    docs = (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.status != "archived")
                            .order_by(KnowledgeDoc.created_at))).all()
    return {"items": [doc_out(d, counts.get(d.id, 0)) for d in docs]}


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
    return await search(s, tenant_id, doc_ids, body.query)
