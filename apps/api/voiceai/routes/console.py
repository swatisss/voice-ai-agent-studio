"""Human agent console: escalation queue, accept, resolve.

Spec: /api/rest-api.md (Escalations), /architecture/escalation.md (Console lifecycle)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import auth, conversations, mask
from voiceai.db import get_session
from voiceai.models import Call, CallEvent, Conversation, Escalation
from voiceai.routes.calls import call_summary
from voiceai.runtime import escalation as esc_mod
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api/escalations")


class AcceptBody(BaseModel):
    assignee: str = "Specialist"


class ReplyBody(BaseModel):
    text: str


class ResolveBody(BaseModel):
    disposition: str
    resolution_note: str


@router.get("")
async def queue(status: str | None = None, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    q = (
        select(Escalation, Call)
        .join(Call, Call.id == Escalation.call_id)
        .where(Escalation.tenant_id == tenant_id, Call.is_eval.is_(False))
        .order_by(Escalation.created_at.desc())
        .limit(500)
    )
    if status:
        q = q.where(Escalation.status == status)
    rows = (await s.execute(q)).all()
    return {"items": [{**esc_mod.summary(e), "call": call_summary(c)} for e, c in rows]}


@router.get("/{escalation_id}")
async def detail(escalation_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    esc = await esc_mod.get_owned(s, tenant_id, escalation_id)
    call = await s.get(Call, esc.call_id)
    events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == esc.call_id).order_by(CallEvent.seq))).all()
    conv = await s.get(Conversation, call.conversation_id) if call and call.conversation_id else None
    return {
        **esc_mod.summary(esc), "call": call_summary(call) if call else None,
        "human_thread": bool(conv and conversations.is_human_thread(conv)),  # HMC: the console shows the Conversation panel
        "conversation_status": conv.status if conv else None,
        "events": [{"seq": e.seq, "at": e.at.isoformat(), "kind": e.kind, "text": e.text, "data": e.data} for e in events],
    }


@router.post("/{escalation_id}/accept")
async def accept(escalation_id: str, body: AcceptBody, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    return esc_mod.summary(await esc_mod.accept(s, tenant_id, escalation_id, auth.actor(request, body.assignee)))


@router.post("/{escalation_id}/resolve")
async def resolve(escalation_id: str, body: ResolveBody, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    note = mask.text(body.resolution_note) if auth.is_specialist(request) else body.resolution_note  # DESK-06: masked before it is stored
    return esc_mod.summary(await esc_mod.resolve(s, tenant_id, escalation_id, body.disposition, note))


@router.post("/{escalation_id}/messages", status_code=201)
async def reply(escalation_id: str, body: ReplyBody, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    """HMC-03: a typed reply to the customer of an accepted API text conversation."""
    return await conversations.human_reply(s, tenant_id, escalation_id, body.text, auth.actor(request, ""))
