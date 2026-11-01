"""Studio conversations: the playground's full flow and the Studio's views of conversations.

Spec: /api/rest-api.md (Conversations), /architecture/supervisor-routing.md (Playground)
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import conversations
from voiceai.conversations import CreateBody
from voiceai.db import get_session
from voiceai.models import Conversation
from voiceai.routes.calls import MessageBody
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api/conversations")


class StudioCreate(CreateBody):
    scope: Literal["member", "staff"] = "member"


@router.post("", status_code=201)
async def create(body: StudioCreate, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    payload = CreateBody(**body.model_dump(exclude={"scope"}))
    return await conversations.create(s, tenant_id, payload, source="playground", scope=body.scope, app=request.app, base_url=str(request.base_url))


@router.get("")
async def list_conversations(source: str | None = None, status: str | None = None, tenant_id: str = Depends(current_tenant),
                             s: AsyncSession = Depends(get_session)) -> dict:
    q = select(Conversation).where(Conversation.tenant_id == tenant_id).order_by(Conversation.started_at.desc()).limit(200)
    if source:
        q = q.where(Conversation.source == source)
    if status:
        q = q.where(Conversation.status == status)
    rows = (await s.scalars(q)).all()
    return {"items": [{"id": c.id, "source": c.source, "channel": c.channel, "transport": c.transport, "scope": c.scope, "status": c.status,
                       "outcome": c.outcome, "external_id": c.external_id, "transfer_count": c.transfer_count,
                       "started_at": c.started_at.isoformat(), "ended_at": c.ended_at.isoformat() if c.ended_at else None} for c in rows]}


@router.post("/{conversation_id}/messages", response_model=None)
async def message(conversation_id: str, body: MessageBody, request: Request, tenant_id: str = Depends(current_tenant),
                  s: AsyncSession = Depends(get_session)) -> dict | StreamingResponse:
    conv = await conversations.get(s, tenant_id, conversation_id)
    await s.close()
    if "text/event-stream" in request.headers.get("accept", ""):
        conversations._check_text_turn(conv)
        return StreamingResponse(conversations.stream_message(conv, body.text, request.app), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await conversations.message(conv, body.text, request.app)


@router.post("/{conversation_id}/end")
async def end(conversation_id: str, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    conv = await conversations.get(s, tenant_id, conversation_id)
    await s.close()
    return await conversations.end(conv, request.app)


@router.get("/{conversation_id}")
async def detail(conversation_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    conv = await conversations.get(s, tenant_id, conversation_id)
    return await conversations.view(s, conv, include_transcript=True)
