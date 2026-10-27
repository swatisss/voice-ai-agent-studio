"""Call admission: the one decision whether a voice call may start, and how it will run.

Spec: /architecture/call-admission.md, /architecture/tenant-settings.md, /architecture/realtime-voice.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import tenant_settings
from voiceai.config import get_settings
from voiceai.live import pipeline_of
from voiceai.llm.gateway import gateway

Reason = Literal["pipeline_not_allowed", "voice_unavailable"]


@dataclass(frozen=True)
class Refusal:
    reason: Reason


@dataclass(frozen=True)
class CallPlan:
    """How an admitted voice call runs. Never holds a key: the socket reads it from `credential_source`."""

    pipeline: Literal["cascade", "realtime"]
    credential_source: Literal["tenant", "platform"]
    model_ref: str | None = None  # the speech model of a realtime call

    def to_meta(self) -> dict[str, Any]:
        return {"pipeline": self.pipeline, "credential_source": self.credential_source, "model_ref": self.model_ref}

    @classmethod
    def from_meta(cls, meta: dict[str, Any] | None) -> CallPlan | None:
        if not meta or meta.get("pipeline") not in ("cascade", "realtime"):
            return None
        return cls(meta["pipeline"], meta.get("credential_source") or "platform", meta.get("model_ref"))


async def _allowed(s: AsyncSession, tenant_id: str, config: dict[str, Any]) -> bool:
    return pipeline_of(config) in await tenant_settings.allowed_pipelines(s, tenant_id)


async def admit(s: AsyncSession, tenant_id: str, config: dict[str, Any]) -> CallPlan | Refusal:
    """ADM-01: allowlist first, then a usable credential; the source follows MT-11."""
    if not await _allowed(s, tenant_id, config):
        return Refusal("pipeline_not_allowed")
    if pipeline_of(config) == "cascade":
        return CallPlan("cascade", "platform") if get_settings().deepgram_api_key else Refusal("voice_unavailable")
    resolved = await tenant_settings.resolve_openai_key(s, tenant_id)
    if resolved is None:
        return Refusal("voice_unavailable")
    model_ref = gateway().speech_ref((config.get("models") or {}).get("speech"))
    return CallPlan("realtime", "tenant" if resolved[1] == "tenant" else "platform", model_ref)


async def credential(s: AsyncSession, tenant_id: str, plan: CallPlan) -> str | None:
    """The key for a planned call, from the planned source only (ADM-04, ADM-05)."""
    if plan.pipeline == "cascade":
        return get_settings().deepgram_api_key or None
    return await tenant_settings.openai_key_from(s, tenant_id, plan.credential_source)


async def admit_socket(
    s: AsyncSession, tenant_id: str, config: dict[str, Any], stored: dict[str, Any] | None,
) -> tuple[CallPlan, str] | Refusal:
    """When the voice socket opens: the allowlist again, then the key from the call's stored plan (a call created
    before admission existed has none and is admitted as if new)."""
    if not await _allowed(s, tenant_id, config):
        return Refusal("pipeline_not_allowed")
    plan = CallPlan.from_meta(stored)
    if plan is None:
        fresh = await admit(s, tenant_id, config)
        if isinstance(fresh, Refusal):
            return fresh
        plan = fresh
    key = await credential(s, tenant_id, plan)
    return (plan, key) if key else Refusal("voice_unavailable")
