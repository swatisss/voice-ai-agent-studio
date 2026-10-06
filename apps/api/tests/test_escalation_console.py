"""Escalation packets and console lifecycle. Covers: ES-04, ES-05, ES-06, ES-07"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from voiceai.db import sessionmaker
from voiceai.events import bus
from voiceai.llm.gateway import FakeReply
from voiceai.models import Escalation
from voiceai.runtime.escalation import wait_packets

H = {"X-Tenant-Id": "evergreen-members"}
ESC = ("escalate_to_human", {"reason_category": "policy_required", "reason_detail": "Caller wants to appeal"})


async def _escalated_call(client, seeded, fake_llm, packet_reply) -> tuple[str, list]:  # noqa: ANN001
    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        if role == "realtime":
            return FakeReply(tool_calls=[ESC])
        return packet_reply()

    fake_llm(responder)
    sub = bus.subscribe("evergreen-members", {"console"})
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["evergreen-members"]["agent_id"], "channel": "text"})
    call_id = r.json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "I want to appeal my denied claim"})
    created = sub.queue.get_nowait()
    await wait_packets()
    updates = []
    while not sub.queue.empty():
        updates.append(sub.queue.get_nowait())
    bus.unsubscribe(sub)
    return call_id, [created, *updates]


async def test_packet_ready_without_job_worker(client, seeded, fake_llm):
    """Covers: ES-04"""
    packet = {
        "summary": "James wants to appeal denied claim C-31544.", "intent": "claim_appeal", "entities": {"claim_id": "C-31544"},
        "already_tried": ["Looked up claim C-31544: denied"], "escalation_reason": {"category": "policy_required", "detail": "appeal"},
        "sentiment": {"start": "neutral", "end": "frustrated", "trend": "declining"}, "suggested_next_action": "File an appeal.",
        "caller_verified": False,
    }
    call_id, events = await _escalated_call(client, seeded, fake_llm, lambda: packet)
    assert events[0]["type"] == "escalation.created"
    assert events[-1]["type"] == "escalation.updated" and events[-1]["data"]["packet_status"] == "ready"
    assert events[-1]["data"]["packet"]["intent"] == "claim_appeal"


async def test_fallback_packet(client, seeded, fake_llm):
    """Covers: ES-05"""
    def boom():  # noqa: ANN202
        raise RuntimeError("LLM down")

    call_id, events = await _escalated_call(client, seeded, fake_llm, boom)
    async with sessionmaker()() as s:
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        assert esc.packet_status == "fallback"
        assert esc.packet["escalation_reason"]["category"] == "policy_required"
        assert isinstance(esc.packet["already_tried"], list)


async def test_console_lifecycle_rules(client, seeded, fake_llm):
    """Covers: ES-06, ES-07"""
    call_id, _ = await _escalated_call(client, seeded, fake_llm, lambda: (_ for _ in ()).throw(RuntimeError()))
    async with sessionmaker()() as s:
        esc_id = (await s.scalar(select(Escalation).where(Escalation.call_id == call_id))).id
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "appeal_filed", "resolution_note": "Filed the appeal for the caller."})
    assert r.status_code == 409
    r = await client.post(f"/api/escalations/{esc_id}/accept", headers=H, json={"assignee": "Dana"})
    assert r.json()["status"] == "accepted"
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "appeal_filed", "resolution_note": "short"})
    assert r.status_code == 422
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "appeal_filed", "resolution_note": "Filed a standard appeal; 30-day decision."})
    assert r.json()["status"] == "resolved"
    queue = (await client.get("/api/escalations", headers=H, params={"status": "resolved"})).json()["items"]
    assert any(e["id"] == esc_id for e in queue)
    await asyncio.sleep(0)
