"""Adapter: tool calls over the network.

Spec: /architecture/tools-and-skills.md (Execution)
"""
from __future__ import annotations

from typing import Any

import httpx

from voiceai.ports.toolcaller import ToolResponse, ToolTimeout, ToolUnreachable


class HttpToolCaller:
    async def request(
        self, method: str, url: str, *, params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout_s: float = 8.0,
    ) -> ToolResponse:
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.request(method, url, params=params, json=json, headers=headers, timeout=timeout_s)
        except httpx.TimeoutException as exc:
            raise ToolTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ToolUnreachable(str(exc)) from exc
        return _response(resp)


def _response(resp: httpx.Response) -> ToolResponse:
    try:
        body: Any = resp.json()
    except ValueError:
        body = {"text": resp.text}
    return ToolResponse(status_code=resp.status_code, body=body, headers=dict(resp.headers))


def build() -> HttpToolCaller:
    return HttpToolCaller()
