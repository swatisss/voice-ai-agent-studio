"""Outbound calls: target lists, call context and the persona opening.

Spec: /architecture/call-modes.md (Outbound calls)
"""
from __future__ import annotations

import re
from typing import Any

from voiceai.core.errors import ApiError
from voiceai.core.toolcalling import ToolCaller, ToolTimeout, ToolUnreachable

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def brand(tenant_name: str) -> str:
    """'Evergreen Health · Customer Support & Channels' -> 'Evergreen Health'."""
    return tenant_name.split("·")[0].strip() or tenant_name


async def fetch_targets(url: str, caller: ToolCaller) -> list[dict[str, Any]]:
    """Targets from the agent's `targets_url`, fetched through the same port tools use."""
    try:
        resp = await caller.request("GET", url, timeout_s=8)
        if resp.status_code >= 400:
            raise ApiError(502, "targets_unavailable", f"Could not load outbound targets: HTTP {resp.status_code}")
        targets = resp.body.get("targets", [])
    except (ToolTimeout, ToolUnreachable, AttributeError) as exc:
        raise ApiError(502, "targets_unavailable", f"Could not load outbound targets: {exc}") from exc
    return [t for t in targets if isinstance(t, dict) and t.get("member_ref")]


def build_context(target: dict[str, Any]) -> dict[str, Any]:
    """Call context stored on the call: the target's context plus who is being called."""
    member_ref = str(target["member_ref"])
    return {
        **(target.get("context") or {}),
        "member_ref": member_ref,
        "first_name": target.get("first_name", ""),
        "member_id": member_ref.split("-", 1)[-1],
    }


def render_opening(persona: dict[str, Any], context: dict[str, Any], tenant_name: str) -> str:
    """The first agent utterance of an outbound call (OB-02)."""
    opening = (persona.get("opening") or "").strip()
    if opening:
        return _PLACEHOLDER.sub(lambda m: str(context.get(m.group(1), "")), opening).strip()
    name = persona.get("name") or "your assistant"
    callee = context.get("first_name") or "the policyholder"
    first = f"Hello, may I speak with {callee}? This is {name} calling from {brand(tenant_name)}."
    return f"{first} {(persona.get('disclosure') or '').strip()}".strip()


def context_lines(context: dict[str, Any]) -> str:
    """Prompt `call_context`: one '- key: value' line each; the member ID is never to be read aloud."""
    if not context:
        return "- (no context)"
    return "\n".join(
        f"- member_id: {v} (never read aloud)" if k == "member_id" else f"- {k}: {v}"
        for k, v in context.items() if k != "member_ref"
    )
