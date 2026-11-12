"""Compliance evidence for the Compliance page (not tenant-scoped).

Spec: /product/compliance-evidence.md, /api/rest-api.md (Compliance)
"""
from __future__ import annotations

from fastapi import APIRouter

from voiceai import compliance

router = APIRouter(prefix="/api/compliance")


@router.get("/evidence")
async def evidence() -> dict:
    return compliance.evidence(compliance.load_report())
