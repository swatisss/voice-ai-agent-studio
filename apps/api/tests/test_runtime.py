"""Agent runtime, triggers and call endpoints.

Covers: RT-01, RT-02, RT-03, RT-04, RT-05, RT-06, RT-07, RT-08, RT-09, ES-01, ES-02, ES-03, ES-08, API-01, API-02, API-03
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from tests.conftest import script
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply, LLMError
from voiceai.models import Agent, Call, CallEvent, Escalation, Job
from voiceai.runtime.session import AgentSession

H = {"X-Tenant-Id": "evergreen-members"}
VERIFY = ("verify_member", {"member_id": "482913", "date_of_birth": "1986-04-12"})


async def _start(client, seeded, channel: str = "text") -> str:  # noqa: ANN001
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["evergreen-members"]["agent_id"], "channel": channel})
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


async def _events(call_id: str) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())


async def _say(client, call_id: str, text: str) -> dict[str, Any]:  # noqa: ANN001
    r = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


async def test_greeting_then_disclosure(client, seeded):
    """Covers: RT-01"""
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["evergreen-members"]["agent_id"], "channel": "text"})
    assert r.json()["greeting"].startswith("Thanks for calling Evergreen Health member services, this is Ava. I'm a virtual assistant")


async def test_tool_round_trip_and_usage(client, seeded, fake_llm):
    """Covers: RT-03, RT-09"""
    seen: list[list[dict]] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        seen.append(messages)
        if len(seen) == 1:
            return FakeReply(tool_calls=[VERIFY])
        return FakeReply(text="Thanks Maria, you're verified.")

    fake_llm(responder)
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "My ID is 482913, April 12 1986")
    assert out["reply"] == "Thanks Maria, you're verified."
    kinds = [e.kind for e in await _events(call_id)]
    assert kinds == ["assistant", "user", "tool_call", "tool_result", "assistant"]
    assert any(m["role"] == "tool" and '"verified": true' in m["content"] for m in seen[1])
    async with sessionmaker()() as s:
        call = await s.get(Call, call_id)
        assert call.tokens_in == 200 and call.llm_cost_usd > 0 and call.caller_ref == "EVG-482913"


async def test_max_tool_rounds(client, seeded, fake_llm):
    """Covers: RT-04"""
    fake_llm(lambda role, m, t: FakeReply(tool_calls=[("find_providers", {"specialty": "derm"})]))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "find me a dermatologist")
    assert "wasn't able" in out["reply"]
    assert sum(1 for e in await _events(call_id) if e.kind == "tool_call") == 4


async def test_end_call_queues_single_analysis(client, seeded, fake_llm):
    """Covers: RT-05, RT-08"""
    fake_llm(script(FakeReply(text="Goodbye!", tool_calls=[("end_call", {"summary": "done"})])))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "That's all, thanks")
    assert out["ended"] is True
    r = await client.post(f"/api/calls/{call_id}/end", headers=H)
    assert r.json()["status"] == "ended"
    async with sessionmaker()() as s:
        n = await s.scalar(select(func.count()).select_from(Job).where(Job.kind == "analyze_call", Job.payload["call_id"].as_string() == call_id))
        assert n == 1


async def test_llm_outage_escalates_then_holds(client, seeded, fake_llm):
    """Covers: RT-06, RT-02"""
    calls = {"n": 0}

    def responder(role, m, t):  # noqa: ANN001, ANN202
        calls["n"] += 1
        raise LLMError("all models failed")

    fake_llm(responder)
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "hello")
    assert "having trouble" in out["reply"] and out["escalated"] is True
    held = await _say(client, call_id, "are you there?")
    assert held["reply"].startswith("A specialist will be with you shortly")
    assert calls["n"] == 1
    async with sessionmaker()() as s:
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        assert esc.reason_category == "other"


async def test_safety_screen(client, seeded, fake_llm):
    """Covers: ES-01"""
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "I have chest pain right now")
    assert "call 911" in out["reply"] and out["escalated"]
    async with sessionmaker()() as s:
        assert (await s.scalar(select(Escalation).where(Escalation.call_id == call_id))).reason_category == "safety"


async def test_no_answer_streak_escalates(client, seeded, fake_llm):
    """Covers: ES-02"""
    fake_llm(script(
        FakeReply(tool_calls=[("search_knowledge", {"query": "quantum lattice gauge"})]),
        FakeReply(tool_calls=[("search_knowledge", {"query": "chromodynamics boson"})]),
        FakeReply(text="I don't have approved information on that."),
    ))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "Tell me about quantum lattice gauge coverage")
    assert out["escalated"]
    async with sessionmaker()() as s:
        assert (await s.scalar(select(Escalation).where(Escalation.call_id == call_id))).reason_category == "knowledge_gap"


async def test_tool_error_streak_escalates(client, seeded, fake_llm):
    """Covers: ES-03"""
    fake_llm(script(
        FakeReply(tool_calls=[VERIFY]),
        FakeReply(tool_calls=[("get_claim_status", {"claim_id": "C-99999"})]),
        FakeReply(tool_calls=[("get_claim_status", {"claim_id": "C-99998"})]),
        FakeReply(text="I couldn't find that claim."),
    ))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "claim status please, 482913 april 12 1986")
    assert out["escalated"]
    async with sessionmaker()() as s:
        assert (await s.scalar(select(Escalation).where(Escalation.call_id == call_id))).reason_category == "tool_failure"


async def test_double_escalate_single_row(client, seeded, fake_llm):
    """Covers: ES-08"""
    esc = ("escalate_to_human", {"reason_category": "caller_requested", "reason_detail": "wants a person"})
    fake_llm(script(FakeReply(tool_calls=[esc, esc])))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "Let me talk to a person")
    assert out["reply"].startswith("I'm connecting you with a specialist")
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Escalation).where(Escalation.call_id == call_id)) == 1


async def test_text_and_simulation_behave_identically(client, seeded, fake_llm):
    """Covers: RT-07"""
    def make():  # noqa: ANN202
        return script(FakeReply(tool_calls=[VERIFY]), FakeReply(text="You're verified."))

    fake_llm(make())
    text_id = await _start(client, seeded)
    await _say(client, text_id, "482913 April 12 1986")
    fake_llm(make())
    async with sessionmaker()() as s:
        call = Call(tenant_id="evergreen-members", agent_id=seeded["evergreen-members"]["agent_id"],
                    agent_version_id=seeded["evergreen-members"]["version_id"], channel="simulation", is_eval=True)
        s.add(call)
        await s.commit()
    sim = await AgentSession.open(call.id, "evergreen-members")
    await sim.start()
    await sim.reply("482913 April 12 1986")
    strip = lambda evs: [(e.kind, e.text, e.data.get("name")) for e in evs]  # noqa: E731
    assert strip(await _events(text_id)) == strip(await _events(call.id))


async def test_unpublished_agent_and_wrong_channel(client, seeded):
    """Covers: API-01, API-02, API-03"""
    async with sessionmaker()() as s:
        a = Agent(tenant_id="evergreen-members", name="Draft only", draft_config={})
        s.add(a)
        await s.commit()
    r = await client.post("/api/calls", headers=H, json={"agent_id": a.id, "channel": "text"})
    assert r.status_code == 409 and r.json()["error"] == "agent_not_published"
    voice_id = await _start(client, seeded, "voice")
    r = await client.post(f"/api/calls/{voice_id}/messages", headers=H, json={"text": "hi"})
    assert r.status_code == 409 and r.json()["error"] == "wrong_channel"
    r = await client.post("/api/calls", headers=H, json={"agent_id": a.id, "channel": "fax"})
    assert r.status_code == 422 and set(r.json()) == {"error", "detail"}
