"""Port: performing one agent tool call.

Spec: /architecture/tools-and-skills.md (Execution)

The runtime decides *what* to call and what to make of the answer; this port decides *how* the
request travels. That split is what lets a relative tool URL run in-process today and cross the
network to an extracted service tomorrow, with no change to the runtime - and it is where an MCP
transport plugs in.

An implementation MUST raise `ToolTimeout` when the call exceeds `timeout_s` and
`ToolUnreachable` for any transport failure. An HTTP status is not a failure: a 404 or a 500 comes
back as a `ToolResponse`, because the runtime reports those to the model differently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolResponse:
    status_code: int
    body: Any  # the parsed JSON body, or {"text": <raw>} when it was not JSON
    headers: dict[str, str] = field(default_factory=dict)


class ToolTimeout(Exception):
    """The tool did not answer within its timeout."""


class ToolUnreachable(Exception):
    """The request never completed: connection refused, DNS failure, protocol error."""


@runtime_checkable
class ToolCaller(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float = 8.0,
    ) -> ToolResponse: ...
