"""The one authorised way to read a stored frame.

Spec: /architecture/media-storage.md, /api/rest-api.md

There is no public URL, no signed URL and no path a browser can guess. An object whose tenant does
not match is reported as not found, indistinguishably from one that never existed - as is one
retention has already removed (MS-05, VI-13).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session
from voiceai.core.errors import ApiError
from voiceai.core.tenancy import current_tenant
from voiceai.modules.evidence import media

router = APIRouter(prefix="/api")


@router.get("/media/{media_id}")
async def get_media(
    media_id: str,
    tenant_id: str = Depends(current_tenant),
    s: AsyncSession = Depends(get_session),
) -> Response:
    found = await media.read_frame(s, tenant_id, media_id)
    if found is None:
        raise ApiError(404, "not_found", "No such media object.")
    data, content_type = found
    # A frame is caller content, so nothing may cache it on the way to the browser.
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/media/samples/catalog")
async def sample_catalog(tenant_id: str = Depends(current_tenant)) -> dict:
    """The synthetic demo images the Test call page offers when there is no camera (IMG-02, IMG-04).

    Listed, not uploaded: every entry is a file shipped in this repository, and nothing here
    generates one (IMG-01).
    """
    from voiceai.modules.evidence import assets

    return {"samples": assets.sample_catalog(), "references": assets.reference_catalog()}
