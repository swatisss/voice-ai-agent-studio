"""The retention job: delete expired frames, then queue the next run.

Spec: /architecture/media-storage.md, /architecture/jobs-and-events.md

This is the one recurring job in the service, and it recurs without a scheduler. The handler
prunes, then enqueues itself with `run_after` six hours out under a fixed dedupe key, so a
duplicate can never pile up and a restart that re-enqueues it is harmless (JB-06).

A cron facility for one job would be more machinery than the job is worth; `run_after` plus a
dedupe key is already exactly what the queue does.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from voiceai.core import jobs
from voiceai.core.db import sessionmaker, utcnow
from voiceai.core.tables import Job, Tenant
from voiceai.modules.evidence import media

log = logging.getLogger("voiceai.media")

KIND = "prune_media"
INTERVAL = timedelta(hours=6)


def dedupe_key(tenant_id: str) -> str:
    return f"{KIND}:{tenant_id}"


@jobs.register(KIND)
async def prune_media(tenant_id: str, payload: dict[str, Any]) -> None:
    async with sessionmaker()() as s:
        try:
            await media.prune_expired(s, tenant_id)
            await s.commit()
        finally:
            # Re-arm even if pruning raised, or one bad object would stop retention forever.
            await _arm(tenant_id)


async def _arm(tenant_id: str) -> None:
    async with sessionmaker()() as s:
        await jobs.enqueue(
            s, tenant_id, KIND, {}, dedupe_key=dedupe_key(tenant_id),
        )
        job = await s.scalar(
            select(Job).where(Job.dedupe_key == dedupe_key(tenant_id), Job.status == "queued")
        )
        if job is not None:
            job.run_after = utcnow() + INTERVAL
        await s.commit()


async def arm_all() -> None:
    """Queue the first run for every tenant, at start-up. Idempotent by dedupe key."""
    async with sessionmaker()() as s:
        tenant_ids = list((await s.scalars(select(Tenant.id))).all())
    for tenant_id in tenant_ids:
        await _arm(tenant_id)
    if tenant_ids:
        log.info("media retention armed for %d tenant(s)", len(tenant_ids))
