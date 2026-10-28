"""Member memory in the Studio: list, restore, erase, export.

Spec: /api/rest-api.md (Member memory), /architecture/agent-memory.md, /ui/member-memory.md
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import memory
from voiceai.db import get_session
from voiceai.errors import ApiError
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api/members")


@router.get("/{member_ref}/memory")
async def member_memory(member_ref: str, agent_id: str | None = None, tenant_id: str = Depends(current_tenant),
                        s: AsyncSession = Depends(get_session)) -> dict:
    view = await memory.member_view(s, tenant_id, member_ref, agent_id)
    if view is None:
        raise ApiError(404, "member_memory_not_found", "Nothing is remembered about this member")
    return view


@router.post("/{member_ref}/memory/{memory_id}/restore")
async def restore(member_ref: str, memory_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    try:
        item = await memory.restore(s, tenant_id, member_ref, memory_id)
    except ValueError as exc:
        raise ApiError(409, "not_retired", "Only a retired memory can be restored") from exc
    if item is None:
        raise ApiError(404, "memory_not_found", "Memory not found")
    await s.commit()
    return memory.item_dict(item)


@router.post("/{member_ref}/memory/erase")
async def erase(member_ref: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    count = await memory.erase(s, tenant_id, member_ref)
    await s.commit()
    return {"erased": count}


@router.get("/{member_ref}/memory/export")
async def export(member_ref: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> Response:
    body = await memory.export(s, tenant_id, member_ref)
    return Response(json.dumps(body, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="memory-{member_ref}.json"'})
