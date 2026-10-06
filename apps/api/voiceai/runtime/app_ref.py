"""Holds the running FastAPI app so tools can call relative URLs in-process.

Spec: /architecture/tools-and-skills.md (Execution, step 5)
"""
from __future__ import annotations

from typing import Any

APP: Any | None = None
