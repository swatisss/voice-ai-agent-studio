"""Phone-number to agent (or front desk) mapping.

Spec: /architecture/telephony.md (Phone numbers), /api/rest-api.md (Phone numbers and telephony), /architecture/supervisor-routing.md
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.models import Agent, PhoneNumber
from voiceai.schemas import E164_RE
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api")


class PhoneNumberIn(BaseModel):
    e164: str
    target: Literal["agent", "front_desk"] = "agent"
    agent_id: str | None = None
    label: str | None = Field(default=None, max_length=120)

    @field_validator("e164")
    @classmethod
    def _e164(cls, v: str) -> str:
        v = v.strip()
        if not E164_RE.fullmatch(v):
            raise ValueError("e164 must look like +15551234567")
        return v


def out(n: PhoneNumber, agent_name: str | None) -> dict[str, Any]:
    return {"id": n.id, "e164": n.e164, "target": n.target or "agent", "agent_id": n.agent_id, "agent_name": agent_name, "label": n.label, "created_at": n.created_at.isoformat()}


@router.get("/phone-numbers")
async def list_numbers(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.execute(
        select(PhoneNumber, Agent.name).outerjoin(Agent, Agent.id == PhoneNumber.agent_id)
        .where(PhoneNumber.tenant_id == tenant_id).order_by(PhoneNumber.e164)
    )).all()
    return {"items": [out(n, name) for n, name in rows]}


@router.post("/phone-numbers")
async def add_number(body: PhoneNumberIn, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    agent = None
    if body.target == "front_desk":  # TEL-12: the supervisor picks the agent
        if body.agent_id:
            raise ApiError(422, "invalid_agent", "A front-desk number has no agent")
    else:
        agent = await s.scalar(select(Agent).where(Agent.id == body.agent_id, Agent.tenant_id == tenant_id)) if body.agent_id else None
        if agent is None:
            raise ApiError(422, "invalid_agent", "agent_id is not an agent of this business unit")
    if await s.scalar(select(PhoneNumber.id).where(PhoneNumber.e164 == body.e164)):
        raise ApiError(409, "number_in_use", "That number is already routed to an agent")
    row = PhoneNumber(tenant_id=tenant_id, e164=body.e164, target=body.target, agent_id=agent.id if agent else None, label=body.label)
    s.add(row)
    await s.commit()
    return out(row, agent.name if agent else None)


@router.delete("/phone-numbers/{number_id}", status_code=204)
async def remove_number(number_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    row = await s.scalar(select(PhoneNumber).where(PhoneNumber.id == number_id, PhoneNumber.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "number_not_found", "Phone number not found")
    await s.delete(row)
    await s.commit()
    return Response(status_code=204)
