"""API keys and webhooks managed from the Studio.

Spec: /api/rest-api.md (API keys and webhooks), /api/public-api.md (API keys), /architecture/webhooks.md
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import webhooks
from voiceai.db import get_session, utcnow
from voiceai.errors import ApiError
from voiceai.models import ApiKey, WebhookDelivery, WebhookEndpoint
from voiceai.public import keys
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api")


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scope: Literal["member", "staff"]
    rate_limit_per_min: int = Field(default=120, ge=10, le=6000)
    max_concurrent_voice: int = Field(default=10, ge=0, le=200)


class KeyUpdate(BaseModel):
    model_config = {"extra": "forbid"}  # API-10: the scope cannot change
    name: str | None = Field(default=None, min_length=1, max_length=60)
    rate_limit_per_min: int | None = Field(default=None, ge=10, le=6000)
    max_concurrent_voice: int | None = Field(default=None, ge=0, le=200)


async def _key(s: AsyncSession, tenant_id: str, key_id: str) -> ApiKey:
    row = await s.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "api_key_not_found", "API key not found")
    return row


@router.get("/api-keys")
async def list_keys(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at.desc()))).all()
    return {"items": [keys.out(k) for k in rows]}


@router.post("/api-keys", status_code=201)
async def create_key(body: KeyCreate, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row, raw = await keys.create(s, tenant_id, body.name.strip(), body.scope, body.rate_limit_per_min, body.max_concurrent_voice)
    await s.commit()
    return {**keys.out(row), "key": raw}  # PUB-01: the only response that carries the key


@router.put("/api-keys/{key_id}")
async def update_key(key_id: str, body: KeyUpdate, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row = await _key(s, tenant_id, key_id)
    if body.name is not None and body.name.strip() != row.name:
        if await s.scalar(select(ApiKey.id).where(ApiKey.tenant_id == tenant_id, ApiKey.name == body.name.strip())):
            raise ApiError(409, "name_taken", f"A key named '{body.name.strip()}' already exists")
        row.name = body.name.strip()
    if body.rate_limit_per_min is not None:
        row.rate_limit_per_min = body.rate_limit_per_min
    if body.max_concurrent_voice is not None:
        row.max_concurrent_voice = body.max_concurrent_voice
    await s.commit()
    return keys.out(row)


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_key(key_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    row = await _key(s, tenant_id, key_id)
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        await s.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- webhooks
class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: list[str]
    include_transcript: bool = False
    enabled: bool = True


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=500)
    events: list[str] | None = None
    include_transcript: bool | None = None
    enabled: bool | None = None


async def _endpoint(s: AsyncSession, tenant_id: str, endpoint_id: str) -> WebhookEndpoint:
    row = await s.scalar(select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id, WebhookEndpoint.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "webhook_not_found", "Webhook endpoint not found")
    return row


@router.get("/webhooks")
async def list_webhooks(tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    rows = (await s.scalars(select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant_id).order_by(WebhookEndpoint.created_at))).all()
    return {"items": [webhooks.out(e) for e in rows]}


@router.post("/webhooks", status_code=201)
async def create_webhook(body: WebhookCreate, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row, secret = await webhooks.create_endpoint(s, tenant_id, body.url.strip(), body.events, body.include_transcript, body.enabled)
    await s.commit()
    return {**webhooks.out(row), "secret": secret}


@router.put("/webhooks/{endpoint_id}")
async def update_webhook(endpoint_id: str, body: WebhookUpdate, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row = await _endpoint(s, tenant_id, endpoint_id)
    if body.url is not None:
        if not webhooks.valid_url(body.url.strip()):
            raise ApiError(422, "invalid_url", "Use an https:// URL")
        row.url = body.url.strip()
    if body.events is not None:
        row.events = webhooks.check_events(body.events)
    if body.include_transcript is not None:
        row.include_transcript = body.include_transcript
    if body.enabled is not None:
        row.enabled = body.enabled
    await s.commit()
    return webhooks.out(row)


@router.post("/webhooks/{endpoint_id}/rotate")
async def rotate_webhook(endpoint_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row = await _endpoint(s, tenant_id, endpoint_id)
    secret = webhooks.rotate(row)
    await s.commit()
    return {"secret": secret}


@router.delete("/webhooks/{endpoint_id}", status_code=204)
async def delete_webhook(endpoint_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    row = await _endpoint(s, tenant_id, endpoint_id)
    await s.delete(row)
    await s.commit()
    return Response(status_code=204)


@router.get("/webhooks/{endpoint_id}/deliveries")
async def deliveries(endpoint_id: str, status: str | None = None, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    await _endpoint(s, tenant_id, endpoint_id)
    q = (select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint_id, WebhookDelivery.tenant_id == tenant_id)
         .order_by(WebhookDelivery.created_at.desc()).limit(200))
    if status:
        q = q.where(WebhookDelivery.status == status)
    return {"items": [webhooks.delivery_out(d) for d in (await s.scalars(q)).all()]}


@router.post("/webhooks/deliveries/{delivery_id}/resend")
async def resend(delivery_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    row = await s.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id, WebhookDelivery.tenant_id == tenant_id))
    if row is None:
        raise ApiError(404, "delivery_not_found", "Delivery not found")
    await webhooks.resend(s, row)
    await s.commit()
    return webhooks.delivery_out(row)
