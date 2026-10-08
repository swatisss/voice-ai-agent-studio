"""Database-backed background job queue with an in-process worker.

Spec: /architecture/jobs-and-events.md (Job queue)
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import traceback
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import engine, sessionmaker, utcnow
from voiceai.core.tables import Job

log = logging.getLogger("voiceai.jobs")

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]  # (tenant_id, payload)
HANDLERS: dict[str, Handler] = {}
MAX_ATTEMPTS = 3
CONCURRENCY = 2
POLL_SECONDS = 1.0


DECLARED_KINDS = ("analyze_call", "draft_fix", "run_eval")  # every job kind this service runs


def register(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def install_handlers() -> None:
    """Import the modules that own each job kind, then check the declared set arrived (MOD-08).

    Registration is a decorator side effect, so a dropped import used to fail silently: the job
    row recorded "no handler", retried to MAX_ATTEMPTS and gave up, taking the whole analysis ->
    cluster -> proposal chain with it. Every entry point that drains or works the queue calls
    this, so a missing handler is a start-up error instead.
    """
    from voiceai.modules.learning import analyze, evaluate, propose  # noqa: F401

    missing = [kind for kind in DECLARED_KINDS if kind not in HANDLERS]
    if missing:
        raise RuntimeError(f"job handlers not registered: {', '.join(missing)}")


async def enqueue(
    session: AsyncSession, tenant_id: str, kind: str, payload: dict[str, Any], dedupe_key: str | None = None
) -> Job:
    """Create a job unless a non-failed job with the same dedupe key exists (JB-04). Caller commits."""
    if dedupe_key:
        existing = await session.scalar(
            select(Job).where(Job.dedupe_key == dedupe_key, Job.status != "failed")
        )
        if existing:
            return existing
    job = Job(tenant_id=tenant_id, kind=kind, payload=payload, dedupe_key=dedupe_key)
    session.add(job)
    await session.flush()
    return job


async def reset_stale() -> int:
    """Jobs left running by a previous process go back to the queue (JB-03)."""
    async with sessionmaker()() as s:
        res = await s.execute(update(Job).where(Job.status == "running").values(status="queued"))
        await s.commit()
        return res.rowcount or 0


async def _claim() -> Job | None:
    async with sessionmaker()() as s:
        stmt = (
            select(Job)
            .where(Job.status == "queued", Job.run_after <= utcnow())
            .order_by(Job.created_at)
            .limit(1)
        )
        if engine().dialect.name != "sqlite":
            stmt = stmt.with_for_update(skip_locked=True)
        job = await s.scalar(stmt)
        if not job:
            return None
        job.status = "running"
        await s.commit()
        return job


async def run_job(job: Job) -> None:
    handler = HANDLERS.get(job.kind)
    error: str | None = None
    try:
        if handler is None:
            raise RuntimeError(f"no handler for job kind '{job.kind}'")
        await handler(job.tenant_id, job.payload)
    except Exception:  # noqa: BLE001 - the queue records any failure
        error = traceback.format_exc(limit=5)
        log.warning("job %s (%s) failed: %s", job.id, job.kind, error.splitlines()[-1])
    async with sessionmaker()() as s:
        db_job = await s.get(Job, job.id)
        if db_job is None:
            return
        if error is None:
            db_job.status = "done"
        else:
            db_job.attempts += 1
            db_job.last_error = error
            if db_job.attempts < MAX_ATTEMPTS:
                db_job.status = "queued"
                db_job.run_after = utcnow() + timedelta(seconds=5 * db_job.attempts)
            else:
                db_job.status = "failed"
        await s.commit()


async def drain(max_jobs: int = 100) -> int:
    """Run queued jobs inline until none are due (tests and CLI)."""
    n = 0
    while n < max_jobs:
        job = await _claim()
        if job is None:
            break
        await run_job(job)
        n += 1
    return n


class Worker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._sem = asyncio.Semaphore(CONCURRENCY)
        self._running: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        await reset_stale()
        self._task = asyncio.create_task(self._loop(), name="job-worker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        for t in list(self._running):
            t.cancel()

    @property
    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        while True:
            try:
                await self._sem.acquire()
                job = await _claim()
                if job is None:
                    self._sem.release()
                    await asyncio.sleep(POLL_SECONDS)
                    continue
                task = asyncio.create_task(self._run(job))
                self._running.add(task)
                task.add_done_callback(self._running.discard)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("job worker loop error")
                self._sem.release()
                await asyncio.sleep(POLL_SECONDS)

    async def _run(self, job: Job) -> None:
        try:
            await run_job(job)
        finally:
            self._sem.release()


worker = Worker()
