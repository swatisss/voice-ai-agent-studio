"""Job queue and event bus. Covers: JB-01, JB-02, JB-03, JB-04, JB-05"""
from __future__ import annotations

from sqlalchemy import update

from voiceai.core import jobs
from voiceai.core.db import sessionmaker, utcnow
from voiceai.adapters.eventbus.inprocess import InProcessEventBus
from voiceai.ports.eventbus import EventBus
from voiceai.core.tables import Job, Tenant


async def _tenant() -> None:
    async with sessionmaker()() as s:
        s.add(Tenant(id="t1", name="T1"))
        await s.commit()


async def _run_due() -> None:
    async with sessionmaker()() as s:  # make retries due immediately
        await s.execute(update(Job).where(Job.status == "queued").values(run_after=utcnow()))
        await s.commit()
    await jobs.drain()


async def test_retry_then_success(database):
    """Covers: JB-01"""
    await _tenant()
    attempts = {"n": 0}

    @jobs.register("flaky")
    async def flaky(tenant_id, payload):  # noqa: ANN001, ANN202
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise RuntimeError("boom")

    async with sessionmaker()() as s:
        job = await jobs.enqueue(s, "t1", "flaky", {})
        await s.commit()
    for _ in range(3):
        await _run_due()
    async with sessionmaker()() as s:
        j = await s.get(Job, job.id)
        assert j.status == "done" and j.attempts == 2


async def test_fails_after_three_attempts(database):
    """Covers: JB-02"""
    await _tenant()

    @jobs.register("always_fails")
    async def always(tenant_id, payload):  # noqa: ANN001, ANN202
        raise ValueError("nope")

    async with sessionmaker()() as s:
        job = await jobs.enqueue(s, "t1", "always_fails", {})
        await s.commit()
    for _ in range(4):
        await _run_due()
    async with sessionmaker()() as s:
        j = await s.get(Job, job.id)
        assert j.status == "failed" and j.attempts == 3 and "nope" in j.last_error


async def test_stale_running_reset_and_dedupe(database):
    """Covers: JB-03, JB-04"""
    await _tenant()
    async with sessionmaker()() as s:
        a = await jobs.enqueue(s, "t1", "x", {}, dedupe_key="k1")
        b = await jobs.enqueue(s, "t1", "x", {}, dedupe_key="k1")
        assert a.id == b.id
        a.status = "running"
        await s.commit()
    assert await jobs.reset_stale() == 1
    async with sessionmaker()() as s:
        assert (await s.get(Job, a.id)).status == "queued"


def test_events_are_tenant_scoped():
    """Covers: JB-05"""
    bus = InProcessEventBus()
    assert isinstance(bus, EventBus)  # the adapter satisfies the port
    sub = bus.subscribe("tenant-a", {"console"})
    bus.publish("tenant-b", "console", "escalation.created", {})
    assert sub.queue.empty()
    bus.publish("tenant-a", "console", "escalation.created", {"id": 1})
    assert sub.queue.get_nowait()["data"] == {"id": 1}
