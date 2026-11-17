"""WhatsApp: sender administration and the signed Twilio inbound and status webhooks.

Spec: /architecture/whatsapp-channel.md, /api/rest-api.md (WhatsApp senders), /architecture/telephony.md (Request security),
/architecture/multi-tenancy.md
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import telephony, whatsapp
from voiceai.config import get_settings
from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.models import Agent, WhatsappSender
from voiceai.tenancy import current_tenant

log = logging.getLogger("voiceai.whatsapp")
router = APIRouter(prefix="/api")
webhooks = APIRouter(prefix="/api/channels/twilio/whatsapp")

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


class SenderIn(BaseModel):
    address: str
    mode: Literal["sandbox", "production"] = "sandbox"
    target: Literal["agent", "front_desk"] = "agent"
    agent_id: str | None = None
    label: str | None = Field(default=None, max_length=120)

    @field_validator("address")
    @classmethod
    def _address(cls, v: str) -> str:
        v = v.strip()
        if not whatsapp.ADDRESS_RE.fullmatch(v):
            raise ValueError("address must look like whatsapp:+14155238886")
        return v


def out(row: WhatsappSender, agent_name: str | None) -> dict[str, Any]:
    return {"id": row.id, "address": row.address, "mode": row.mode, "target": row.target, "agent_id": row.agent_id,
            "agent_name": agent_name, "label": row.label, "created_at": row.created_at.isoformat()}


@router.get("/whatsapp-senders")
async def list_senders(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.execute(select(WhatsappSender, Agent.name).outerjoin(Agent, Agent.id == WhatsappSender.agent_id)
                            .where(WhatsappSender.tenant_id == tenant_id).order_by(WhatsappSender.address))).all()
    return {"items": [out(r, name) for r, name in rows]}


@router.post("/whatsapp-senders", status_code=201)
async def add_sender(body: SenderIn, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = None
    if body.target == "front_desk":
        if body.agent_id:
            raise ApiError(422, "invalid_agent", "A front-desk sender has no agent")
    else:
        agent = await s.scalar(select(Agent).where(Agent.id == body.agent_id, Agent.tenant_id == tenant_id)) if body.agent_id else None
        if agent is None:
            raise ApiError(422, "invalid_agent", "agent_id is not an agent of this business unit")
    if await s.scalar(select(WhatsappSender.id).where(WhatsappSender.address == body.address)):
        raise ApiError(409, "sender_in_use", "That WhatsApp address is already routed")
    row = WhatsappSender(tenant_id=tenant_id, address=body.address, mode=body.mode, target=body.target,
                         agent_id=agent.id if agent else None, label=body.label)
    s.add(row)
    await s.commit()
    return out(row, agent.name if agent else None)


@router.delete("/whatsapp-senders/{sender_id}", status_code=204)
async def remove_sender(sender_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    row = await s.scalar(select(WhatsappSender).where(WhatsappSender.id == sender_id, WhatsappSender.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "sender_not_found", "WhatsApp sender not found")
    await s.delete(row)
    await s.commit()
    return Response(status_code=204)


def _xml() -> Response:
    return Response(content=EMPTY_TWIML, media_type="application/xml")


async def _verified(request: Request) -> dict[str, str] | None:
    """The form of a signed Twilio request (WA-02). None = configured off or not configured: answer 200 and do nothing;
    a bad signature is 403. The signed URL is PUBLIC_BASE_URL plus the path, port kept (TEL-02, TEL-10)."""
    s = get_settings()
    form = await request.form()
    params = {key: [str(v) for v in form.getlist(key)] for key in form.keys()}
    if not (s.twilio_auth_token and s.twilio_account_sid and s.public_base_url):
        return None
    if s.twilio_validate_signature:
        query = request.url.query
        url = telephony.public_url(request.url.path + (f"?{query}" if query else ""))
        if not telephony.valid_signature(s.twilio_auth_token, url, params, request.headers.get("x-twilio-signature")):
            raise ApiError(403, "invalid_signature", "Bad or missing X-Twilio-Signature")
    return {k: v[0] for k, v in params.items() if v}


@webhooks.post("/inbound")
async def inbound(request: Request, background: BackgroundTasks) -> Response:
    """WA-02, WA-03: answer at once with an empty `<Response/>`; the turn and its reply run in the background."""
    params = await _verified(request)
    if params is None:
        return _xml()
    message = whatsapp.parse_inbound(params)
    if message is None:
        log.warning("WhatsApp message without a usable From or To ignored")
        return _xml()
    thread_id = await whatsapp.accept_inbound(message)
    if thread_id:
        background.add_task(whatsapp.process_inbound, request.app, thread_id, message)
    return _xml()


@webhooks.post("/status")
async def status(request: Request) -> Response:
    """WA-07: a delivery receipt updates the matching `human` event."""
    params = await _verified(request)
    if params is not None:
        await whatsapp.apply_receipt(params)
    return _xml()
