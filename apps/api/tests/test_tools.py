"""Tool execution. Covers: TS-01, TS-02, TS-03, TS-04, TS-05, TS-06, TS-08"""
from __future__ import annotations

import json

from fastapi import FastAPI, Request

from voiceai.runtime.state import CallState
from voiceai.runtime.tools import MAX_RESULT_CHARS, ToolExecutor, render_url, truncate

echo = FastAPI()
SEEN: list[dict] = []


@echo.api_route("/{path:path}", methods=["GET", "POST"])
async def _echo(path: str, request: Request):  # noqa: ANN201
    SEEN.append({"path": "/" + path, "query": str(request.url.query), "headers": dict(request.headers)})
    if path.startswith("missing"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": "nope"}, status_code=404)
    if path == "verify":
        return {"verified": True, "member_ref": "EVG-482913"}
    return {"ok": True}


def _ex(state: CallState, tools: list[dict]) -> ToolExecutor:
    SEEN.clear()
    return ToolExecutor("t1", "c1", tools, state, app=echo)


async def test_verification_gate_blocks_without_request():
    """Covers: TS-01"""
    ex = _ex(CallState(), [{"name": "get_benefits", "url": "/benefits", "requires_verification": True}])
    result, ok = await ex.execute("get_benefits", "{}")
    assert result["error"] == "identity_not_verified" and ok and SEEN == []


async def test_verification_tool_sets_state_and_member_header():
    """Covers: TS-02, TS-08"""
    state = CallState()
    ex = _ex(state, [{"name": "verify_member", "method": "POST", "url": "/verify", "is_verification": True},
                     {"name": "get_benefits", "url": "/benefits", "requires_verification": True}])
    await ex.execute("get_benefits", "{}")
    assert SEEN == []
    await ex.execute("verify_member", json.dumps({"member_id": "482913", "date_of_birth": "1986-04-12"}))
    assert "x-member-ref" not in SEEN[-1]["headers"]
    assert state.verified and state.verified_member_ref == "EVG-482913"
    await ex.execute("get_benefits", "{}")
    assert SEEN[-1]["headers"]["x-member-ref"] == "EVG-482913"


async def test_url_rendering_and_query():
    """Covers: TS-03"""
    assert render_url("/mock/healthcare/claims/{claim_id}", {"claim_id": "C-20931", "include": "lines"}) == (
        "/mock/healthcare/claims/C-20931", {"include": "lines"})
    ex = _ex(CallState(), [{"name": "get_claim_status", "url": "/mock/healthcare/claims/{claim_id}"}])
    await ex.execute("get_claim_status", json.dumps({"claim_id": "C-20931", "include": "lines"}))
    assert SEEN[-1]["path"] == "/mock/healthcare/claims/C-20931" and SEEN[-1]["query"] == "include=lines"


async def test_http_error_counts_as_tool_error():
    """Covers: TS-04"""
    ex = _ex(CallState(), [{"name": "lookup", "url": "/missing"}])
    result, ok = await ex.execute("lookup", "{}")
    assert result["error"] == "http_404" and ok is False


def test_truncation():
    """Covers: TS-05"""
    assert len(truncate({"text": "x" * 5000})) == MAX_RESULT_CHARS


async def test_builtin_name_rejected(client, seeded, members_headers):
    """Covers: TS-06"""
    r = await client.post("/api/tools", headers=members_headers, json={"name": "search_knowledge", "url": "/x"})
    assert r.status_code == 422
