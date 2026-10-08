"""Adapter: send each tool call by the transport its URL implies.

Spec: /architecture/tools-and-skills.md (Execution, step 5)

Absolute URLs go over the network; relative ones are served in-process by this application. This
is the single place that decision is made - it used to be duplicated in the tool executor and in
outbound target fetching. When a module is extracted, its relative prefix gets a base URL here and
starts crossing the network with no change to any module.
"""
from __future__ import annotations

from typing import Any

from voiceai.adapters.tools.http import HttpToolCaller
from voiceai.ports.toolcaller import ToolCaller, ToolResponse


class RoutingToolCaller:
    def __init__(self, local: ToolCaller | None = None, remote: ToolCaller | None = None) -> None:
        self.local = local  # None: there is no in-process app, so everything goes over the network
        self.remote = remote or HttpToolCaller()

    def caller_for(self, url: str) -> ToolCaller:
        absolute = url.startswith(("http://", "https://"))
        return self.remote if absolute or self.local is None else self.local

    async def request(
        self, method: str, url: str, *, params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout_s: float = 8.0,
    ) -> ToolResponse:
        return await self.caller_for(url).request(
            method, url, params=params, json=json, headers=headers, timeout_s=timeout_s
        )


def build(app: Any | None = None) -> RoutingToolCaller:
    from voiceai.adapters.tools.asgi import AsgiToolCaller

    return RoutingToolCaller(local=AsgiToolCaller(app) if app is not None else None)
