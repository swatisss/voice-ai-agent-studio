"""CP-0042: the safety screen at the front desk, a transfer inside the first routed text turn, medical history is not an emergency.

Typed (text) conversations on the fake LLM, modelled on the pre-demo QA of 2026-11-13.

Covers: RTE-21, XFR-10, ES-11, ES-12
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.test_agent_transfer import Script, say
from tests.test_capability_catalog import run_index_jobs
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent, Conversation, Escalation
from voiceai.routing import catalog, front_desk
from voiceai.runtime import escalation

H = {"X-Tenant-Id": "northgate-health"}
EMERGENCY = "I have chest pain and I can't breathe properly."
HINDI_EMERGENCY = "मुझे सीने में दर्द है"
PARTNER = "I have a question about adding my partner to my policy."
TRANSFER = ("transfer_to_agent", {"reason": "add_partner_to_policy", "summary": "Caller wants to add their partner to the policy."})


def prefer(*order: str):  # noqa: ANN201
    """Stage A that ranks the candidates in `order` (the first present wins by a clear margin)."""
    async def fake(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
        pool = set(candidates or set())
        ranked = [a for a in order if a in pool]
        return [{"agent_id": a, "score": 0.95 if i == 0 else 0.2} for i, a in enumerate(ranked)]

    return fake


@pytest.fixture
async def ready(client, seeded, fake_llm, monkeypatch):  # noqa: ANN001
    brain = Script()
    fake_llm(brain)
    await run_index_jobs()
    monkeypatch.setattr(catalog, "stage_a", prefer(seeded["care"]["agent_id"], seeded["claims"]["agent_id"], seeded["sales"]["agent_id"]))
    return seeded, brain


async def _desk(**patch) -> None:  # noqa: ANN003
    async with sessionmaker()() as s:
        await front_desk.update(s, "northgate-health", front_desk.FrontDeskPatch(**patch))
        await s.commit()


async def _open(client, message: str) -> dict:  # noqa: ANN001
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member", "message": message})
    assert r.status_code == 201, r.text
    return r.json()


async def _segments(cid: str) -> list[Call]:
    async with sessionmaker()() as s:
        return (await s.scalars(select(Call).where(Call.conversation_id == cid).order_by(Call.segment))).all()


async def test_emergency_at_the_front_desk_is_not_routed(client, ready, fake_llm, monkeypatch):  # noqa: ANN001
    """Covers: RTE-21"""
    seeded, brain = ready
    care = seeded["care"]["agent_id"]
    await _desk(default_agents={"member": care}, routing_mode="decision_model")
    fake_llm(Script(FakeReply(text="the model must not answer an emergency")))

    async def no_stage_a(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("Stage A must not run with a default agent")

    monkeypatch.setattr(catalog, "stage_a", no_stage_a)
    out = await _open(client, EMERGENCY)
    assert out["agent"]["id"] == care and "call 999" in out["messages"][-1]["text"]
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, out["conversation_id"])
        seg = await s.get(Call, conv.current_call_id)
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == seg.id))
        lines = (await s.scalars(select(CallEvent.text).where(CallEvent.call_id == seg.id, CallEvent.kind == "assistant"))).all()
    last = conv.routing[-1]
    assert last["method"] == "safety" and last["agent_id"] == care and last["stage_b"] is None and last["fallbacks"] == []
    assert seg.end_reason == "handoff" and esc is not None and esc.reason_category == "safety"
    assert "call 999" in lines[-1] and seg.meta["handoff"]["summary"] == EMERGENCY
    assert brain.calls.get("realtime", 0) == 0 and brain.calls.get("router", 0) == 0

    # no default agent: the Stage A leader takes it, still without a decision-model or router request
    await _desk(default_agents={"member": None})
    monkeypatch.setattr(catalog, "stage_a", prefer(seeded["claims"]["agent_id"], care))
    out2 = await _open(client, HINDI_EMERGENCY)
    async with sessionmaker()() as s:
        conv2 = await s.get(Conversation, out2["conversation_id"])
    assert out2["agent"]["id"] == seeded["claims"]["agent_id"] and conv2.routing[-1]["method"] == "safety"
    assert out2["messages"][-1]["text"].startswith("अगर")  # the Hindi safety message (LANG-08)


async def test_transfer_in_the_first_routed_turn_reaches_the_caller(client, ready, fake_llm):  # noqa: ANN001
    """Covers: XFR-10"""
    seeded, _ = ready
    care, claims = seeded["care"]["agent_id"], seeded["claims"]["agent_id"]
    await _desk(default_agents={"member": care})
    brain = Script(FakeReply(tool_calls=[TRANSFER]), "Adding a partner means a new quote; I can help with that.")
    fake_llm(brain)
    out = await _open(client, PARTNER)
    assert out["transferred"] is True and out["agent"]["id"] != care
    texts = [m["text"] for m in out["messages"]]  # the front desk's greeting, the first agent's intro, the next agent's intro and answer
    assert texts[1] == "You're now with our member services team." and "new quote" in texts[-1] and len(texts) >= 4
    first, second = await _segments(out["conversation_id"])
    assert (first.end_reason, first.outcome) == ("transfer", "transferred") and second.routed_by == "transfer"
    async with sessionmaker()() as s:
        user_lines = (await s.scalars(select(CallEvent.text).where(CallEvent.call_id == second.id, CallEvent.kind == "user"))).all()
        conv = await s.get(Conversation, out["conversation_id"])
    assert user_lines == [PARTNER] and conv.routing[-1]["trigger"] == "transfer"
    assert brain.calls["realtime"] == 2  # the first agent's turn, then the receiving agent's answer


def test_history_is_not_an_emergency():
    """Covers: ES-11"""
    for line in ("I had a heart attack last year and I'm on blood thinners", "history of stroke", "chest pain when I was 40",
                 "I had chest pain in 2019", "Previously I had a stroke, in the past"):
        assert not escalation.safety_match(line), line
    for line in ("I have chest pain right now", "I'm having a heart attack", "I think I'm having a stroke", "I had a heart attack",
                 "I want to end my life, it was last year too", "heart attack last year and I can't breathe", "मुझे सीने में दर्द है"):
        assert escalation.safety_match(line), line


async def test_underwriting_history_continues_the_call(client, ready, fake_llm):  # noqa: ANN001
    """Covers: ES-12"""
    seeded, _ = ready
    brain = Script("Thank you, noted. Do you take any other medication?")
    fake_llm(brain)
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["sales"]["agent_id"], "channel": "text"})
    assert r.status_code == 200, r.text
    call_id = r.json()["call_id"]
    r = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "Full medical underwriting please, I had a heart attack last year"})
    assert r.status_code == 200, r.text
    assert "noted" in r.json()["reply"] and not r.json()["escalated"] and brain.calls["realtime"] == 1
    async with sessionmaker()() as s:
        assert await s.scalar(select(Escalation).where(Escalation.call_id == call_id)) is None
