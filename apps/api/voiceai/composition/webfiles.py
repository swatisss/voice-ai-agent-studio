"""Serving the statically exported web app from the API process.

Spec: /architecture/deployment.md, /decisions/adr-0005-single-service.md
"""
from __future__ import annotations

import posixpath

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException


def next_segment_path(path: str) -> str | None:
    """Next.js 16 static export requests `dir/__next.a.b.__PAGE__.txt` but writes `dir/__next.a/b/__PAGE__.txt`."""
    directory, base = posixpath.split(path)
    if not (base.startswith("__next.") and base.endswith(".txt")) or base in ("__next._tree.txt", "__next._full.txt"):
        return None
    parts = base[len("__next."):-len(".txt")].split(".")
    if len(parts) < 2:
        return None
    return posixpath.join(directory, "__next." + parts[0], *parts[1:-1], parts[-1] + ".txt")


class WebFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # noqa: ANN001, ANN201
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            response = None
        if response is not None and response.status_code != 404:
            return response
        alt = next_segment_path(path)
        if alt:
            return await super().get_response(alt, scope)
        if response is None:
            raise StarletteHTTPException(404)
        return response
