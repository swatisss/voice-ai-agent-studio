"""Adapter: tool calls served in-process by this application, with no network hop.

Spec: /architecture/tools-and-skills.md (Execution, step 5)

Holds the ASGI application it calls, which is why no module needs a global reference to it.
"""
from __future__ import annotations

from typing import Any

import httpx

from voiceai.adapters.tools.http import _response
from voiceai.ports.toolcaller import ToolResponse, ToolTimeout, ToolUnreachable

INTERNAL = "http://internal"


class AsgiToolCaller:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def request(
        self, method: str, url: str, *, params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout_s: float = 8.0,
    ) -> ToolResponse:
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=INTERNAL) as client:
                resp = await client.request(method, url, params=params, json=json, headers=headers, timeout=timeout_s)
        except httpx.TimeoutException as exc:
            raise ToolTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ToolUnreachable(str(exc)) from exc
        return _response(resp)


def build(app: Any) -> AsgiToolCaller:
    return AsgiToolCaller(app)
