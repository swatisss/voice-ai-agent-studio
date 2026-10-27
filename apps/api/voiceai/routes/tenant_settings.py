"""Tenant settings: pipeline allowlist, platform-key fallback and the tenant's own OpenAI key.

Spec: /api/rest-api.md (Tenant settings), /architecture/tenant-settings.md
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import tenant_settings as ts
from voiceai.db import get_session
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api/tenant-settings")


class SettingsBody(BaseModel):
    allowed_pipelines: list[Literal["cascade", "realtime"]] | None = None
    openai_platform_fallback: bool | None = None


class KeyBody(BaseModel):
    api_key: str = Field(max_length=400)


@router.get("")
async def get_settings_(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    return await ts.view(s, tenant_id)


@router.put("")
async def put_settings(body: SettingsBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await ts.update(s, tenant_id, body.allowed_pipelines, body.openai_platform_fallback)
    await s.commit()
    return await ts.view(s, tenant_id)


@router.put("/openai-key")
async def put_key(body: KeyBody, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await ts.set_openai_key(s, tenant_id, body.api_key.strip())
    await s.commit()
    openai = (await ts.view(s, tenant_id))["openai"]
    return {k: openai[k] for k in ("key_set", "key_last4", "key_updated_at")}


@router.delete("/openai-key", status_code=204)
async def delete_key(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    await ts.delete_openai_key(s, tenant_id)
    await s.commit()
    return Response(status_code=204)
