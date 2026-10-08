"""The ASGI entry point (`voiceai.main:app`). The application is built in composition/.

Spec: /architecture/system-overview.md, /architecture/modular-structure.md
"""
from __future__ import annotations

from voiceai.composition.app import app, create_app, lifespan
from voiceai.composition.webfiles import WebFiles, next_segment_path

__all__ = ["WebFiles", "app", "create_app", "lifespan", "next_segment_path"]
