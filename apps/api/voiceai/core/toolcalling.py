"""The tool caller modules use, behind the ToolCaller port.

Spec: /architecture/tools-and-skills.md (Execution)

`tool_caller(app)` routes relative URLs in-process against that application and absolute ones over
the network; with no application it sends everything over the network, which is what background
work and the CLI want. Modules ask here rather than naming an adapter, so extracting a service
later is a change to the routing adapter alone.
"""
from __future__ import annotations

from typing import Any

from voiceai.adapters.tools.routing import build
from voiceai.ports.toolcaller import ToolCaller, ToolResponse, ToolTimeout, ToolUnreachable

__all__ = ["ToolCaller", "ToolResponse", "ToolTimeout", "ToolUnreachable", "tool_caller"]


def tool_caller(app: Any | None = None) -> ToolCaller:
    return build(app)
