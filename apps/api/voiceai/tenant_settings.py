"""Tenant settings and credentials: pipeline allowlist, own OpenAI key and its resolution for realtime calls.

Spec: /architecture/tenant-settings.md, /architecture/multi-tenancy.md (rule 7)
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import vault
from voiceai.errors import ApiError
from voiceai.call_settings import pipeline_of
from voiceai.llm.gateway import gateway
from voiceai.models import Agent, AgentVersion, Tenant, TenantCredential, TenantSettings

log = logging.getLogger("voiceai.tenant_settings")

PIPELINES = ("cascade", "realtime")
DEFAULT_PIPELINES = ["cascade"]
_KEY_RE = re.compile(r"^sk-\S{17,297}$")  # 20-300 characters, no whitespace


async def _row(s: AsyncSession, tenant_id: str) -> TenantSettings | None:
    return await s.get(TenantSettings, tenant_id)


async def _credential(s: AsyncSession, tenant_id: str, provider: str = "openai") -> TenantCredential | None:
    return await s.scalar(select(TenantCredential).where(TenantCredential.tenant_id == tenant_id, TenantCredential.provider == provider))


async def allowed_pipelines(s: AsyncSession, tenant_id: str) -> list[str]:
    row = await _row(s, tenant_id)
    return list(row.allowed_pipelines) if row else list(DEFAULT_PIPELINES)


async def view(s: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """MT-05: the settings as the API shows them; the key itself never appears (MT-09)."""
    row = await _row(s, tenant_id)
    cred = await _credential(s, tenant_id)
    usable = cred is not None and vault.decrypt(cred.ciphertext) is not None  # MT-10: unreadable counts as not set
    return {
        "allowed_pipelines": list(row.allowed_pipelines) if row else list(DEFAULT_PIPELINES),
        "openai": {
            "key_set": usable,
            "key_last4": cred.last4 if usable and cred else None,
            "key_updated_at": (cred.updated_at or cred.created_at).isoformat() if usable and cred else None,
            "platform_fallback": row.openai_platform_fallback if row else True,
        },
    }


async def _ensure_row(s: AsyncSession, tenant_id: str) -> TenantSettings:
    row = await _row(s, tenant_id)
    if row is None:
        row = TenantSettings(tenant_id=tenant_id, allowed_pipelines=list(DEFAULT_PIPELINES), openai_platform_fallback=True)
        s.add(row)
    return row


async def agents_using(s: AsyncSession, tenant_id: str, pipeline: str) -> list[str]:
    """Names of the tenant's agents whose draft or published version runs on `pipeline`."""
    names: list[str] = []
    for agent in (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id).order_by(Agent.name))).all():
        version = await s.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None
        if pipeline_of(agent.draft_config or {}) == pipeline or (version and pipeline_of(version.config) == pipeline):
            names.append(agent.name)
    return names


async def update(s: AsyncSession, tenant_id: str, allowed: list[str] | None, platform_fallback: bool | None) -> None:
    """MT-07: validate and store; dropping a pipeline still in use is refused."""
    if allowed is not None:
        if not allowed or "cascade" not in allowed or any(p not in PIPELINES for p in allowed):
            raise ApiError(422, "invalid_settings", "allowed_pipelines must include 'cascade' and only 'cascade' or 'realtime'")
        allowed = [p for p in PIPELINES if p in allowed]
        current = await allowed_pipelines(s, tenant_id)
        for dropped in (p for p in current if p not in allowed):
            in_use = await agents_using(s, tenant_id, dropped)
            if in_use:
                raise ApiError(409, "pipeline_in_use", ", ".join(in_use))
    row = await _ensure_row(s, tenant_id)
    if allowed is not None:
        row.allowed_pipelines = allowed
    if platform_fallback is not None:
        row.openai_platform_fallback = platform_fallback


async def set_openai_key(s: AsyncSession, tenant_id: str, api_key: str) -> None:
    """MT-09, MT-10: format check, then store encrypted with the last four characters for display."""
    if not _KEY_RE.match(api_key or ""):
        raise ApiError(422, "invalid_key", "An OpenAI key starts with 'sk-' and has 20 to 300 characters without spaces")
    try:
        token = vault.encrypt(api_key)
    except vault.VaultUnavailable as exc:
        raise ApiError(503, "secrets_unavailable", "Key storage is not configured on this server (TENANT_SECRETS_KEY)") from exc
    cred = await _credential(s, tenant_id)
    if cred is None:
        s.add(TenantCredential(tenant_id=tenant_id, provider="openai", ciphertext=token, last4=api_key[-4:]))
    else:
        cred.ciphertext, cred.last4 = token, api_key[-4:]


async def delete_openai_key(s: AsyncSession, tenant_id: str) -> None:
    cred = await _credential(s, tenant_id)
    if cred is not None:
        await s.delete(cred)


async def ensure_pipeline_allowed(s: AsyncSession, tenant_id: str, config: dict[str, Any]) -> None:
    """MT-06: raise `pipeline_not_allowed` when the config's pipeline is not in the tenant's allowlist."""
    pipeline = pipeline_of(config)
    if pipeline not in await allowed_pipelines(s, tenant_id):
        raise ApiError(422, "pipeline_not_allowed", f"The {pipeline} voice pipeline is not enabled for this business unit")


async def openai_key_from(s: AsyncSession, tenant_id: str, source: str) -> str | None:
    """The OpenAI key a realtime call of this tenant may use from one source: `tenant` (its own stored key) or
    `platform` (the platform key, only while the tenant allows the fallback)."""
    if source == "tenant":
        cred = await _credential(s, tenant_id)
        return vault.decrypt(cred.ciphertext) if cred is not None else None
    row = await _row(s, tenant_id)
    if row is None or row.openai_platform_fallback:
        return gateway().provider_key("openai") or None
    return None


async def resolve_openai_key(s: AsyncSession, tenant_id: str) -> tuple[str, str] | None:
    """MT-11: (key, source) for a realtime call of this tenant - own key, else the platform key if allowed, else None."""
    for source in ("tenant", "platform"):
        key = await openai_key_from(s, tenant_id, source)
        if key:
            return key, source
    return None


async def grandfather(s: AsyncSession) -> list[str]:
    """MT-12: at startup, tenants without a settings row that already run a realtime agent keep realtime."""
    changed: list[str] = []
    for tenant_id in (await s.scalars(select(Tenant.id))).all():
        if await _row(s, tenant_id) is None and await agents_using(s, tenant_id, "realtime"):
            s.add(TenantSettings(tenant_id=tenant_id, allowed_pipelines=list(PIPELINES), openai_platform_fallback=True))
            changed.append(tenant_id)
    if changed:
        log.info("realtime pipeline kept for existing tenants: %s", ", ".join(changed))
    return changed
