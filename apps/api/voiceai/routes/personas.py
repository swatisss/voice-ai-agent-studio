"""Persona library CRUD.

Spec: /architecture/personas.md, /api/rest-api.md (Personas)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.call_settings import persona_dict
from voiceai.models import Agent, Persona
from voiceai.schemas import VOICE_RE, PersonaIn
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api")


async def _agents_using(s: AsyncSession, tenant_id: str) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for a in (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id))).all():
        pid = (a.draft_config or {}).get("persona_id")
        if pid:
            used.setdefault(pid, []).append(a.name)
    return used


async def _get(s: AsyncSession, tenant_id: str, persona_id: str) -> Persona:
    p = await s.scalar(select(Persona).where(Persona.id == persona_id, Persona.tenant_id == tenant_id))
    if not p:
        raise ApiError(404, "persona_not_found", "Persona not found")
    return p


@router.get("/personas")
async def list_personas(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    used = await _agents_using(s, tenant_id)
    rows = (await s.scalars(select(Persona).where(Persona.tenant_id == tenant_id).order_by(Persona.name))).all()
    return {"items": [{**persona_dict(p), "description": p.description, "used_by": used.get(p.id, [])} for p in rows]}


@router.post("/personas")
async def create_persona(body: PersonaIn, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    p = Persona(tenant_id=tenant_id, **body.model_dump())
    s.add(p)
    await s.commit()
    return {**persona_dict(p), "description": p.description, "used_by": []}


@router.put("/personas/{persona_id}")
async def update_persona(persona_id: str, body: PersonaIn, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    p = await _get(s, tenant_id, persona_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    await s.commit()
    return {**persona_dict(p), "description": p.description, "used_by": (await _agents_using(s, tenant_id)).get(p.id, [])}


@router.delete("/personas/{persona_id}", status_code=204)
async def delete_persona(persona_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    p = await _get(s, tenant_id, persona_id)
    users = (await _agents_using(s, tenant_id)).get(p.id, [])
    if users:  # PER-05
        raise ApiError(409, "persona_in_use", f"Used by: {', '.join(users)}")
    await s.delete(p)
    await s.commit()
    return Response(status_code=204)


class SampleIn(BaseModel):
    voice: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=300)


@router.post("/personas/sample")
async def voice_sample(body: SampleIn, tenant_id: str = Depends(current_tenant)) -> Response:  # noqa: ARG001
    """QA-13 (P4): the persona's voice reading a line, so it is heard before a live call (/architecture/personas.md)."""
    import httpx

    from voiceai.config import get_settings

    if not VOICE_RE.fullmatch(body.voice):
        raise ApiError(422, "invalid_voice", "Unknown voice")
    key = get_settings().deepgram_api_key
    if not key:
        raise ApiError(503, "voice_unavailable", "No speech key is configured, so the voice cannot be played")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post("https://api.deepgram.com/v1/speak", params={"model": body.voice, "encoding": "mp3"},
                                     headers={"Authorization": f"Token {key}"}, json={"text": body.text})
    except httpx.HTTPError as exc:
        raise ApiError(502, "voice_unavailable", "The speech service did not answer") from exc
    if resp.status_code >= 400:
        raise ApiError(502, "voice_unavailable", f"The speech service refused the request ({resp.status_code})")
    return Response(content=resp.content, media_type="audio/mpeg")
