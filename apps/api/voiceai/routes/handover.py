"""Signed Twilio callbacks of a phone warm handover, and the Agent Desk phone endpoints.

Spec: /architecture/phone-warm-handover.md (Callbacks, Agent Desk), /architecture/agent-desk.md, /api/rest-api.md
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import auth, handover, telephony
from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.tenancy import current_tenant

router = APIRouter()
callbacks = APIRouter(prefix="/api/telephony/twilio/handover")


async def _callback(request: Request, call_id: str, handle: Callable[[str, dict[str, str]], Awaitable[bool]]) -> Response:
    """TEL-20: signed, 200 with an empty body, idempotent, 404 for a call without a handover."""
    form = await telephony.verified_form(request)
    if not await handle(call_id, form):
        raise ApiError(404, "handover_not_found", "This call has no handover")
    return Response(status_code=200)


@callbacks.post("/specialist/{call_id}")
async def specialist(call_id: str, request: Request) -> Response:
    return await _callback(request, call_id, handover.on_specialist_status)


@callbacks.post("/conference/{call_id}")
async def conference(call_id: str, request: Request) -> Response:
    return await _callback(request, call_id, handover.on_conference_event)


@callbacks.post("/recording/{call_id}")
async def recording(call_id: str, request: Request) -> Response:
    return await _callback(request, call_id, handover.on_recording)


# ---------------------------------------------------------------- Agent Desk: the specialist's browser as a phone (TEL-25)
class Presence(BaseModel):
    ready: bool


def _email(request: Request) -> str:
    user = auth.current_user(request)
    return user.email if user else ""


@router.post("/api/desk/phone-token")
async def phone_token(request: Request) -> dict:
    if not handover.voice_sdk_configured():
        raise ApiError(503, "phone_unavailable", "The Twilio API key is not configured")
    identity = handover.identity_of(_email(request))
    return {"token": handover.access_token(identity), "identity": identity, "ttl_seconds": handover.TOKEN_TTL_S}


@router.put("/api/desk/phone-presence")
async def phone_presence(body: Presence, request: Request, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await handover.set_presence(s, tenant_id, _email(request), body.ready)
    return {"ready": body.ready, "expires_in_s": handover.PRESENCE_TTL_S if body.ready else 0}
