"""FastAPI application: API, voice WebSocket, SSE, mock API, job worker and the static web app.

Spec: /architecture/system-overview.md, /architecture/deployment.md, /decisions/adr-0005-single-service.md
"""
from __future__ import annotations

import logging
import posixpath
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException

# register job handlers
import voiceai.learning.analyze  # noqa: F401
import voiceai.learning.evaluate  # noqa: F401
import voiceai.learning.propose  # noqa: F401
from voiceai import db
from voiceai.config import get_settings
from voiceai.errors import ApiError, install_handlers
from voiceai.jobs import worker
from voiceai.mock.routes import router as mock_router
from voiceai.models import Tenant
from voiceai.routes import agents, calls, console, dashboard, insights, knowledge, meta, personas, usecases
from voiceai.runtime import app_ref, escalation

log = logging.getLogger("voiceai")


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db.configure(settings.database_url)
    await db.init_db()
    app_ref.APP = app
    if settings.auto_seed:
        async with db.sessionmaker()() as s:
            empty = (await s.scalar(select(func.count()).select_from(Tenant))) == 0
        if empty:
            from voiceai.seed.loader import seed

            log.info("empty database: seeding demo data")
            await seed(reset=False)
    if settings.jobs_enabled:
        await worker.start()
    yield
    await worker.stop()
    await escalation.wait_packets()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Voice Agent Studio", version="0.1.0", lifespan=lifespan)
    install_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"], allow_headers=["*"],
    )
    for r in (meta.router, agents.router, personas.router, knowledge.router, calls.router, usecases.router, console.router, insights.router, dashboard.router, mock_router):
        app.include_router(r)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def api_not_found(path: str) -> None:  # DEP-02: unknown API paths stay JSON
        raise ApiError(404, "not_found", f"No API route /api/{path}")

    web = settings.web_dist_dir
    if web.exists():
        app.mount("/", WebFiles(directory=web, html=True), name="web")
    return app


app = create_app()
