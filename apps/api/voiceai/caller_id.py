"""Caller identification and the member profile, both read from the business API.

Spec: /architecture/caller-verification.md (Identification), /architecture/agent-memory.md (Reading memory in a call)

Neither result is stored beyond what the specs allow: identification keeps the member reference, first name, method and
attestation on the call (never the full number); the profile is used for one call only.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from voiceai.config import get_settings
from voiceai.runtime.tools import business_client

log = logging.getLogger("voiceai.caller_id")

WITHHELD = {"", "anonymous", "unknown", "restricted", "private"}
ATTESTED = "TN-Validation-Passed-A"


def _absolute(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def identification(match: dict[str, Any], attestation: str | None = None) -> dict[str, Any]:
    """What a call keeps about an identified caller (`calls.meta.identification`)."""
    return {"member_ref": match["member_ref"], "first_name": match["first_name"], "method": "caller_id", "attestation": attestation or None}


def attested(ident: dict[str, Any] | None) -> bool:
    """IDV-05: full carrier attestation, without diversion or passthrough variants."""
    return bool(ident) and (ident.get("attestation") or "") == ATTESTED


async def identify(phone: str | None, app: Any | None = None) -> dict[str, Any] | None:  # noqa: ANN401
    """IDV-01, IDV-06: the member a registered calling number belongs to, or None (unregistered, withheld, unreachable)."""
    raw = (phone or "").strip()
    if raw.lower() in WITHHELD or raw.startswith("client:") or not re.sub(r"\D", "", raw):
        return None
    url = get_settings().member_identify_url
    try:
        async with business_client(_absolute(url), app) as client:
            resp = await client.post(url, json={"phone": raw}, timeout=5)
        body = resp.json() if resp.status_code < 400 else {}
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("caller identification failed: %s", exc)
        return None
    if not body.get("matched") or not body.get("member_ref"):
        return None
    return {"member_ref": str(body["member_ref"]), "first_name": str(body.get("first_name") or "")}


async def profile(member_ref: str, tenant_id: str, call_id: str, app: Any | None = None) -> dict[str, Any] | None:  # noqa: ANN401
    """The verified member's profile for this call only (never stored)."""
    url = get_settings().member_profile_url
    headers = {"X-Member-Ref": member_ref, "X-Tenant-Id": tenant_id, "X-Call-Id": call_id}
    try:
        async with business_client(_absolute(url), app) as client:
            resp = await client.get(url, headers=headers, timeout=5)
        return resp.json() if resp.status_code < 400 else None
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("member profile failed: %s", exc)
        return None


def render_profile(data: dict[str, Any] | None) -> str:
    """`member_profile` in the system prompt: `- key: value` lines."""
    if not data:
        return "- (profile unavailable)"
    lines = [f"- first name: {data.get('first_name') or '(unknown)'}"]
    if data.get("plan_name"):
        lines.append(f"- plan: {data['plan_name']}")
    policies = [f"{p.get('policy_id')} {p.get('product')} ({p.get('status')})" for p in data.get("policies") or []]
    if policies:
        lines.append(f"- policies: {'; '.join(policies)}")
    claims = [f"{c.get('claim_id')} ({c.get('status')})" for c in data.get("open_claims") or []]
    lines.append(f"- open claims: {'; '.join(claims) if claims else 'none'}")
    if data.get("preferred_contact"):
        lines.append(f"- preferred contact: {data['preferred_contact']}")
    return "\n".join(lines)
