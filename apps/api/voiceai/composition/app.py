"""The composition root: build the FastAPI application and wire everything into it.

Spec: /architecture/system-overview.md, /architecture/deployment.md,
      /architecture/modular-structure.md, /decisions/adr-0005-single-service.md

This is the only place that knows which adapter implements which port, which routers exist, and
in what order the process starts and stops. One deployable serves the REST API, the voice
WebSocket, server-sent events, the simulated business API, the job worker and the exported web app.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from voiceai.composition import jobs as job_wiring
from voiceai.composition.webfiles import WebFiles
from voiceai.core import db
from voiceai.core.config import get_settings
from voiceai.core.errors import ApiError, install_handlers
from voiceai.core.jobs import worker
from voiceai.core.tables import Tenant
from voiceai.mock.routes import router as mock_router
from voiceai.routes import agents, calls, console, dashboard, insights, knowledge, meta, personas, usecases
from voiceai.runtime import escalation

log = logging.getLogger("voiceai")

ROUTERS = (
    meta.router, agents.router, personas.router, knowledge.router, calls.router,
    usecases.router, console.router, insights.router, dashboard.router, mock_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db.configure(settings.database_url)
    await db.init_db()
    if settings.auto_seed:
        async with db.sessionmaker()() as s:
            empty = (await s.scalar(select(func.count()).select_from(Tenant))) == 0
        if empty:
            from voiceai.seed.loader import seed  # lazy: seeding reaches across every module

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
    job_wiring.install()  # MOD-08: explicit, and loud if a job kind lost its module
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"], allow_headers=["*"],
    )
    for router in ROUTERS:
        app.include_router(router)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def api_not_found(path: str) -> None:  # DEP-02: unknown API paths stay JSON
        raise ApiError(404, "not_found", f"No API route /api/{path}")

    web = settings.web_dist_dir
    if web.exists():
        app.mount("/", WebFiles(directory=web, html=True), name="web")
    return app


app = create_app()
