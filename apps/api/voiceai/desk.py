"""Agent Desk (specialist) role: allow-listed API, one business unit, masked and reduced responses.

Spec: /architecture/agent-desk.md
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from voiceai import mask

_ID = r"[^/]+"
# (methods, path pattern): everything a specialist may call; any other /api request is refused.
ALLOWED: list[tuple[tuple[str, ...], re.Pattern[str]]] = [(m, re.compile(p)) for m, p in [
    (("GET",), r"^/api/tenants$"),
    (("GET",), r"^/api/events$"),
    (("GET",), r"^/api/escalations(/" + _ID + r")?$"),
    (("POST",), r"^/api/escalations/" + _ID + r"/(accept|resolve|messages)$"),
    (("GET",), r"^/api/calls(/" + _ID + r")?$"),
    (("GET",), r"^/api/insights/clusters(/" + _ID + r")?$"),
    (("GET", "POST"), r"^/api/insights/clusters/" + _ID + r"/comments$"),
    (("GET",), r"^/api/knowledge(/" + _ID + r"|/sources(/" + _ID + r")?)?$"),
    (("POST",), r"^/api/knowledge/search$"),
    (("GET",), r"^/api/agents(/" + _ID + r"(/versions)?)?$"),
    (("GET",), r"^/api/members/" + _ID + r"/memory$"),
    (("POST",), r"^/api/desk/phone-token$"),
    (("PUT",), r"^/api/desk/phone-presence$"),
]]
EVENT_TOPICS = {"console"}
# Cost and learning internals a specialist never receives (DESK-08).
CLUSTER_HIDE = {"est_weekly_cost_usd", "weekly_escalations", "escalations_28d", "dislike_count", "human_answer", "human_answer_by", "proposals"}
CALL_HIDE = {"llm_cost_usd", "tokens_in", "tokens_out", "latency_p50_ms", "scorecard", "version_info"}
FIX_HIDE = {"before_per_week", "after_per_week", "held", "proposal_id"}


def allowed(method: str, path: str) -> bool:
    return any(method in methods and pattern.match(path) for methods, pattern in ALLOWED)


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1")
    return None


def refusal(error: str, detail: str, status: int = 403) -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail}, status_code=status)


def check(scope: Scope, tenant_id: str) -> JSONResponse | None:
    """The refusal for a request outside the role, else `None`; also pins the request to the account's unit."""
    method, path = scope["method"], scope["path"]
    if method == "OPTIONS":
        return None
    if not allowed(method, path):
        return refusal("role_forbidden", "Not available for your role")
    query = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
    asked = _header(scope, b"x-tenant-id") or (query.get("tenant") or [None])[0]
    if asked and asked != tenant_id:
        return refusal("tenant_forbidden", "This account works in one business unit")
    if path == "/api/events":
        topics = {t.strip() for t in (query.get("topics") or [""])[0].split(",") if t.strip()}
        if not topics or not topics <= EVENT_TOPICS:
            return refusal("role_forbidden", "Not available for your role")
    headers = [(k, v) for k, v in scope.get("headers") or [] if k != b"x-tenant-id"]
    headers.append((b"x-tenant-id", tenant_id.encode()))
    scope["headers"] = headers
    return None


def _drop(data: Any, keys: set[str]) -> Any:
    if isinstance(data, list):
        return [_drop(v, keys) for v in data]
    if isinstance(data, dict):
        return {k: _drop(v, keys) for k, v in data.items() if k not in keys}
    return data


def shape(path: str, data: Any, tenant_id: str) -> Any:
    """Reduce a response to what the role needs (the masking pass comes after)."""
    if path.startswith(("/api/calls", "/api/escalations")):
        return _drop(data, CALL_HIDE)
    if path == "/api/tenants" and isinstance(data, dict):
        return {"items": [t for t in data.get("items", []) if t.get("id") == tenant_id]}
    if path.startswith("/api/insights/clusters") and not path.endswith("/comments") and isinstance(data, dict):
        items = data["items"] if "items" in data else [data]
        for c in items:
            for key in CLUSTER_HIDE:
                c.pop(key, None)
            if isinstance(c.get("fix"), dict):
                c["fix"] = {k: v for k, v in c["fix"].items() if k not in FIX_HIDE}
            if "calls" in c:
                c["calls"] = [m for m in c["calls"] if m.get("outcome") == "escalated"]
    return data


def respond(scope: Scope, send: Send, tenant_id: str) -> Send:
    """Wrap `send`: JSON bodies are shaped and masked; event streams and anything else pass through untouched."""
    path = scope["path"]
    state: dict[str, Any] = {"start": None, "body": b"", "json": False}

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            ctype = next((v.decode("latin-1") for k, v in message.get("headers") or [] if k.lower() == b"content-type"), "")
            state["json"] = ctype.startswith("application/json")
            if state["json"]:
                state["start"] = message
            else:
                await send(message)
            return
        if message["type"] != "http.response.body" or not state["json"]:
            await send(message)
            return
        state["body"] += message.get("body", b"")
        if message.get("more_body"):
            return
        try:
            out = json.dumps(mask.walk(shape(path, json.loads(state["body"] or b"null"), tenant_id)), ensure_ascii=False).encode()
        except ValueError:
            out = state["body"]
        start = state["start"]
        start["headers"] = [(k, v) for k, v in start.get("headers") or [] if k.lower() != b"content-length"] + [(b"content-length", str(len(out)).encode())]
        await send(start)
        await send({"type": "http.response.body", "body": out})

    return wrapped


async def serve(app: Any, scope: Scope, receive: Receive, send: Send, tenant_id: str) -> None:
    if (refused := check(scope, tenant_id)) is not None:
        await refused(scope, receive, send)
        return
    await app(scope, receive, respond(scope, send, tenant_id))
