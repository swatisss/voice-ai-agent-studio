"""Tool schemas and execution: built-ins, HTTP tools, verification gate.

Spec: /architecture/tools-and-skills.md, /architecture/agent-runtime.md (Built-in tools)
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from voiceai.core.toolcalling import ToolCaller, ToolTimeout, ToolUnreachable
from voiceai.runtime.state import CallState
from voiceai.schemas import ESCALATION_CATEGORIES

MAX_RESULT_CHARS = 2000
VERIFY_FIRST = "I need to verify your identity first. Can I have your member ID and date of birth?"

BUILTIN_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the approved knowledge base for plan rules, coverage, processes and policies. Call this before answering any such question.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The caller's question in a few words"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Hand the call to a human specialist. Then say exactly the message this tool returns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason_category": {"type": "string", "enum": list(ESCALATION_CATEGORIES)},
                    "reason_detail": {"type": "string", "description": "One sentence: why a human is needed"},
                },
                "required": ["reason_category", "reason_detail"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "End the call after the caller confirms they need nothing else. Say goodbye in the same reply.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string", "description": "One sentence summary of what was resolved"}},
                "required": ["summary"],
            },
        },
    },
]


def tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": tool["name"], "description": tool.get("description", ""), "parameters": tool.get("parameters") or {"type": "object", "properties": {}}},
    }


def all_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return BUILTIN_SCHEMAS + [tool_schema(t) for t in tools]


def render_url(url: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Fill {placeholders} from args; return the URL and the remaining args."""
    remaining = dict(args)

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        value = remaining.pop(key, "")
        return quote(str(value), safe="")

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", sub, url), remaining


def _summary(name: str, status: int | None, body: Any) -> str:
    if isinstance(body, dict):
        if "error" in body:
            return f"{name}: error {body.get('error')}"
        keys = [k for k in ("verified", "status", "claim_id", "auth_id", "plan_name", "remaining", "request_id", "tier", "denial_reason") if k in body]
        if keys:
            parts = ", ".join(f"{k}={json.dumps(body[k]) if isinstance(body[k], (dict, list)) else body[k]}" for k in keys)
            return f"{name}: {parts}"[:160]
        if "claims" in body:
            return f"{name}: {len(body['claims'])} claims"
        if "providers" in body:
            return f"{name}: {len(body['providers'])} providers"
    return f"{name}: HTTP {status}"[:160]


class ToolExecutor:
    """Executes one call's agent tools. How a request travels is the ToolCaller's business."""

    def __init__(self, tenant_id: str, call_id: str, tools: list[dict[str, Any]], state: CallState,
                 caller: ToolCaller) -> None:
        self.tenant_id = tenant_id
        self.call_id = call_id
        self.tools = {t["name"]: t for t in tools}
        self.state = state
        self.caller = caller

    async def execute(self, name: str, raw_args: str) -> tuple[dict[str, Any], bool]:
        """Returns (result, ok). ok=False counts toward the tool-error streak."""
        tool = self.tools.get(name)
        if tool is None:
            return {"error": "unknown_tool", "detail": f"No tool named {name}"}, False
        try:
            args = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return {"error": "invalid_arguments"}, False
        if tool.get("requires_verification") and not self.state.verified:  # TS-01
            self.state.tools_used.append({"name": name, "ok": False, "summary": f"{name}: blocked until identity verified"})
            return {"error": "identity_not_verified", "say": VERIFY_FIRST}, True
        url, rest = render_url(tool["url"], args)
        headers = {"X-Tenant-Id": self.tenant_id, "X-Call-Id": self.call_id}
        if self.state.verified and self.state.verified_member_ref:  # TS-08
            headers["X-Member-Ref"] = self.state.verified_member_ref
        method = tool.get("method", "GET").upper()
        get = method == "GET"
        try:
            resp = await self.caller.request(
                method, url,
                params={k: v for k, v in rest.items() if v is not None} if get else None,
                json=None if get else rest,
                headers=headers, timeout_s=tool.get("timeout_s", 8),
            )
        except ToolTimeout:
            self.state.tools_used.append({"name": name, "ok": False, "summary": f"{name}: timeout"})
            return {"error": "timeout"}, False
        except ToolUnreachable as exc:
            self.state.tools_used.append({"name": name, "ok": False, "summary": f"{name}: connection error"})
            return {"error": "connection_error", "detail": str(exc)[:200]}, False
        body = resp.body
        if resp.status_code >= 400:  # TS-04
            result = {"error": f"http_{resp.status_code}", "detail": json.dumps(body)[:300]}
            self.state.tools_used.append({"name": name, "ok": False, "summary": _summary(name, resp.status_code, body)})
            return result, False
        if tool.get("is_verification") and isinstance(body, dict) and body.get("verified") is True:  # TS-02
            self.state.verified = True
            self.state.verified_member_ref = body.get("member_ref") or self.state.verified_member_ref
        self.state.tools_used.append({"name": name, "ok": True, "summary": _summary(name, resp.status_code, body)})
        return body if isinstance(body, dict) else {"result": body}, True


def truncate(result: Any) -> str:
    text = json.dumps(result, default=str)
    return text[:MAX_RESULT_CHARS]  # TS-05
