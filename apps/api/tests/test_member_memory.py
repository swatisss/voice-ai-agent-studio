"""Member memory: written by the agent after a verified call, read at verification, expired, erased, restored, exported.

Spec: /architecture/agent-memory.md
Covers: MEM-01, MEM-02, MEM-03, MEM-04, MEM-05, MEM-06, MEM-07, MEM-08, MEM-09, MEM-10, MEM-11, MT-13, API-06, API-07, DM-07
"""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select

from voiceai import memory
from voiceai.db import sessionmaker, utcnow
from voiceai.knowledge.embeddings import embed_one
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, Job, MemberMemory, MemoryEvent
from voiceai.runtime.session import AgentSession, create_call

TENANT = "evergreen-care"
H = {"X-Tenant-Id": TENANT}
MARIA = ("verify_member", {"member_id": "482913", "date_of_birth": "1986-04-12"})
PRIYA = ("verify_member", {"member_id": "559804", "date_of_birth": "1992-07-23"})


# ---------------------------------------------------------------- helpers
async def open_session(seeded, agent: str = "care", channel: str = "text") -> AgentSession:  # noqa: ANN001
    async with sessionmaker()() as s:
        call = await create_call(s, TENANT, seeded[agent]["agent_id"], channel)
        await s.commit()
    session = await AgentSession.open(call.id, TENANT)
    await session.start()
    return session


async def verified_call(seeded, fake_llm, verify=PRIYA, said: str = "Thanks.", agent: str = "care") -> AgentSession:  # noqa: ANN001
    """A text call where the caller verifies, says `said`, and the call ends."""
    replies = iter([FakeReply(tool_calls=[verify]), FakeReply(text="You're verified."), FakeReply(text="Noted.")])
    fake_llm(lambda role, messages, tools: next(replies))
    session = await open_session(seeded, agent)
    await session.reply("Here are my details")
    await session.reply(said)
    await session.end("hangup")
    return session


def analysis(extract: dict, decide=None):  # noqa: ANN001, ANN201
    """A fake `analysis` model: the extraction prompt returns `extract`; the update prompt asks `decide(candidate, ids)`."""
    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        prompt = messages[-1]["content"]
        if prompt.startswith("You maintain the memory"):
            return extract
        if prompt.startswith("You keep an agent's memory"):
            candidate = prompt.split("today's call:\n", 1)[1].split("\n", 1)[0]
            ids = re.findall(r"- \[([0-9a-f]+)\]", prompt)
            return decide(candidate, ids) if decide else {"action": "ADD", "target_id": None, "reason": "new"}
        raise AssertionError(f"unexpected prompt for {role}")
    return responder


async def scope(session: AgentSession, member: str) -> list[MemberMemory]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(MemberMemory).where(MemberMemory.tenant_id == TENANT, MemberMemory.agent_id == session.agent_id,
                                                                MemberMemory.member_ref == member))).all())


async def events_of(member: str) -> list[MemoryEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(MemoryEvent).where(MemoryEvent.member_ref == member).order_by(MemoryEvent.at))).all())


async def add_fact(session: AgentSession, member: str, text: str, **extra) -> MemberMemory:  # noqa: ANN003
    async with sessionmaker()() as s:
        m = MemberMemory(tenant_id=TENANT, agent_id=session.agent_id, member_ref=member, kind="fact", category="preference", text=text,
                         expires_at=utcnow() + timedelta(days=30), embedding=await embed_one(text), **extra)
        s.add(m)
        await s.commit()
        return m


# ---------------------------------------------------------------- write path
async def test_extraction_is_queued_only_for_verified_real_calls(client, seeded, fake_llm):
    """Covers: MEM-01"""
    verified = await verified_call(seeded, fake_llm)
    fake_llm(lambda *a: FakeReply(text="Hello."))
    unverified = await open_session(seeded)
    await unverified.reply("Hi")
    await unverified.end("hangup")
    off = await open_session(seeded)
    off.call_settings = off.call_settings.__class__.of({**off.config, "memory": {"enabled": False}})
    off.state.verified, off.state.verified_member_ref = True, "EVG-559804"
    await off.end("hangup")
    async with sessionmaker()() as s:
        sim = Call(tenant_id=TENANT, agent_id=seeded["care"]["agent_id"], agent_version_id=seeded["care"]["version_id"],
                   channel="simulation", is_eval=True, caller_ref="EVG-559804")
        s.add(sim)
        await s.commit()
    simulated = await AgentSession.open(sim.id, TENANT)
    await simulated.end("hangup")
    async with sessionmaker()() as s:
        keys = {j.dedupe_key for j in (await s.scalars(select(Job).where(Job.kind == "extract_memory"))).all()}
    assert keys == {f"extract_memory:{verified.call_id}"}


async def test_a_call_becomes_an_episode_and_facts(client, seeded, fake_llm):
    """Covers: MEM-02"""
    session = await verified_call(seeded, fake_llm, said="Please call me back after 5pm, my daughter Ana usually helps with my claims")
    said_seq = max(e.seq for e in await _events(session.call_id) if e.kind == "user")
    fake_llm(analysis({"episode": "Asked to be called after 5pm and said her daughter helps with claims.", "facts": [
        {"text": "Prefers a call back after 5pm", "category": "preference", "seq": said_seq},
        {"text": "Her daughter Ana helps with her claims", "category": "relationship", "seq": said_seq},
    ]}))
    await memory.extract_memory(TENANT, {"call_id": session.call_id})
    rows = await scope(session, "EVG-559804")
    facts = [m for m in rows if m.kind == "fact"]
    assert len([m for m in rows if m.kind == "episode"]) == 1
    assert sorted(m.category for m in facts) == ["preference", "relationship"] and all(m.status == "active" for m in facts)
    assert all(m.source_call_id == session.call_id and m.source_seq == said_seq for m in facts)
    added = [e for e in await events_of("EVG-559804") if e.action == "added" and e.memory_id in {m.id for m in facts}]
    assert len(added) == 2


async def test_a_changed_preference_supersedes_the_old_fact(client, seeded, fake_llm):
    """Covers: MEM-03"""
    session = await verified_call(seeded, fake_llm, said="Please only email me from now on")
    old = await add_fact(session, "EVG-559804", "Prefers phone calls")
    fake_llm(analysis({"episode": "", "facts": [{"text": "Wants to be contacted by email only", "category": "preference"}]},
                      decide=lambda candidate, ids: {"action": "SUPERSEDE", "target_id": ids[0], "reason": "Contact preference changed"}))
    await memory.extract_memory(TENANT, {"call_id": session.call_id})
    rows = {m.id: m for m in await scope(session, "EVG-559804")}
    retired = rows[old.id]
    new = rows[retired.superseded_by]
    assert retired.status == "retired" and retired.invalid_at is not None and new.status == "active"
    assert new.text == "Wants to be contacted by email only"
    sup = [e for e in await events_of("EVG-559804") if e.action == "superseded"]
    assert len(sup) == 1 and (sup[0].text_before, sup[0].text_after) == ("Prefers phone calls", new.text)


async def test_health_payment_and_identifiers_are_never_stored(client, seeded, fake_llm):
    """Covers: MEM-04"""
    session = await verified_call(seeded, fake_llm, said="I take metformin for my chest pain, card 4111 1111 1111 1111")
    fake_llm(analysis({
        "episode": "The member described chest pain and their medication. They asked about a claim.",
        "facts": [{"text": "Takes metformin for chest pain", "category": "circumstance"},
                  {"text": "Pays with card 4111 1111 1111 1111", "category": "preference"},
                  {"text": "Member ID is EVG-559804", "category": "circumstance"}],
    }))
    await memory.extract_memory(TENANT, {"call_id": session.call_id})
    rows = await scope(session, "EVG-559804")
    assert [m.kind for m in rows] == ["episode"] and rows[0].text == "They asked about a claim."
    stored = " ".join(m.text for m in rows) + " ".join(e.text_after or "" for e in await events_of("EVG-559804"))
    for banned in ("metformin", "pain", "4111", "EVG-559804"):
        assert banned not in stored


# ---------------------------------------------------------------- read path
async def test_memory_reaches_only_the_same_agent_after_verification(client, seeded, fake_llm):
    """Covers: MEM-05, MEM-06, MT-13"""
    seen: list[str] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        seen.append(messages[0]["content"])
        return FakeReply(tool_calls=[MARIA]) if len(seen) == 1 else FakeReply(text="Hello Maria.")

    fake_llm(responder)
    care = await open_session(seeded, "care")
    await care.reply("My ID is 482913, April 12 1986")
    assert "Facts:" not in seen[0] and "- (not verified yet)" in seen[0]                     # MEM-06: nothing before verification
    assert "Prefers a call back after 5pm on weekdays" in seen[1] and "plan: Evergreen Silver PPO" in seen[1]
    assert "Earlier calls:" in seen[1] and len(care.state.memory_used) == 3                  # 2 seeded facts + 1 episode
    loaded = [e for e in await _events(care.call_id) if e.kind == "system" and "memory_used" in e.data]
    assert loaded[0].data["memory_used"] == care.state.memory_used

    seen.clear()
    claims = await open_session(seeded, "claims")                                            # another agent of the same tenant
    await claims.reply("My ID is 482913, April 12 1986")
    assert claims.state.verified and claims.state.memory_used == [] and "Prefers a call back" not in seen[1]
    other = await client.get("/api/members/EVG-482913/memory", headers={"X-Tenant-Id": "evergreen-sandbox"})
    assert other.status_code == 404                                                           # MT-13: never another tenant
    export = (await client.get("/api/members/EVG-482913/memory/export", headers={"X-Tenant-Id": "evergreen-sandbox"})).json()
    assert export["memories"] == [] and export["events"] == []


async def test_every_channel_loads_and_writes_the_same_memory(client, seeded, fake_llm):
    """Covers: MEM-10"""
    used = []
    for channel in ("text", "voice"):  # text and cascade voice share respond()
        replies = iter([FakeReply(tool_calls=[MARIA]), FakeReply(text="Hi Maria.")])
        fake_llm(lambda role, messages, tools: next(replies))
        session = await open_session(seeded, "care", channel)
        await session.reply("482913, April 12 1986")
        await session.end("hangup")
        used.append((session.state.memory_used, session.call_id))
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("the realtime channel brings its own model")))
    driven = await open_session(seeded, "care", "voice")                                      # the realtime pipeline's events
    await driven.caller_turn("482913, April 12 1986")
    await driven.tool_requested(*MARIA)
    await driven.reply_finished("Hi Maria.")
    await driven.end("hangup")
    used.append((driven.state.memory_used, driven.call_id))
    assert used[0][0] == used[1][0] == used[2][0] and len(used[0][0]) == 3
    async with sessionmaker()() as s:
        keys = {j.dedupe_key for j in (await s.scalars(select(Job).where(Job.kind == "extract_memory"))).all()}
    assert keys == {f"extract_memory:{call_id}" for _, call_id in used}


# ---------------------------------------------------------------- expiry, erasure, restore, export
async def test_expired_memory_is_never_read_and_is_purged(client, seeded, fake_llm):
    """Covers: MEM-07"""
    probe = await open_session(seeded)
    async with sessionmaker()() as s:
        old = MemberMemory(tenant_id=TENANT, agent_id=probe.agent_id, member_ref="EVG-482913", kind="fact", category="preference",
                           text="Likes long phone calls", expires_at=utcnow() - timedelta(days=1))
        s.add(old)
        await s.flush()
        s.add(MemoryEvent(tenant_id=TENANT, agent_id=probe.agent_id, member_ref="EVG-482913", memory_id=old.id, action="added",
                          actor="agent", text_after=old.text))
        await s.commit()
        facts, _ = await memory.load(s, TENANT, probe.agent_id, "EVG-482913")
        assert old.id not in {f.id for f in facts}
    await memory.purge_memory(TENANT, {})
    async with sessionmaker()() as s:
        assert await s.get(MemberMemory, old.id) is None
    texts = [(e.text_before, e.text_after, e.reason) for e in await events_of("EVG-482913") if e.memory_id == old.id]
    assert texts and all(t == (None, None, None) for t in texts) and "Likes long phone calls" not in str(texts)


async def test_erase_member_removes_everything_and_leaves_a_record(client, seeded, fake_llm):
    """Covers: MEM-08, API-07"""
    claims = await open_session(seeded, "claims")
    await add_fact(claims, "EVG-482913", "Calls about motor claims")               # memory on a second agent
    r = await client.post("/api/members/EVG-482913/memory/erase", headers=H)
    assert r.status_code == 200 and r.json()["erased"] == 4                         # 3 seeded on Customer Care + 1 here
    async with sessionmaker()() as s:
        assert (await s.scalars(select(MemberMemory).where(MemberMemory.member_ref == "EVG-482913"))).all() == []
    events = await events_of("EVG-482913")
    assert [(e.action, e.text_before, e.text_after, e.memory_id) for e in events] == [("erased", None, None, None)]
    view = (await client.get("/api/members/EVG-482913/memory", headers=H)).json()
    assert (view["facts"], view["episodes"], view["retired"], [e["action"] for e in view["events"]]) == ([], [], [], ["erased"])
    export = (await client.get("/api/members/EVG-482913/memory/export", headers=H)).json()
    assert export["memories"] == [] and [e["action"] for e in export["events"]] == ["erased"]
    assert (await client.get("/api/members/EVG-999999/memory", headers=H)).status_code == 404
    care = await open_session(seeded, "care")
    replies = iter([FakeReply(tool_calls=[MARIA]), FakeReply(text="Hi.")])
    fake_llm(lambda role, messages, tools: next(replies))
    await care.reply("482913, April 12 1986")
    assert care.state.verified and care.state.memory_used == []


async def test_restore_brings_a_retired_fact_back(client, seeded, fake_llm):
    """Covers: MEM-09"""
    probe = await open_session(seeded)
    retired = await add_fact(probe, "EVG-482913", "Prefers letters by post", status="retired", invalid_at=utcnow())
    r = await client.post(f"/api/members/EVG-482913/memory/{retired.id}/restore", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert (await client.post(f"/api/members/EVG-482913/memory/{retired.id}/restore", headers=H)).status_code == 409
    assert [e.action for e in await events_of("EVG-482913") if e.memory_id == retired.id] == ["restored"]
    replies = iter([FakeReply(tool_calls=[MARIA]), FakeReply(text="Hi.")])
    fake_llm(lambda role, messages, tools: next(replies))
    care = await open_session(seeded)
    await care.reply("482913, April 12 1986")
    assert retired.id in care.state.memory_used


async def test_export_and_call_detail_show_memory_with_its_source(client, seeded, fake_llm):
    """Covers: MEM-11, API-06"""
    session = await verified_call(seeded, fake_llm, verify=MARIA, said="Email works better for me now")
    phone_fact = next(m for m in await scope(session, "EVG-482913") if m.text.startswith("Prefers a call back"))
    fake_llm(analysis({"episode": "Asked to be emailed instead of called.", "facts": [{"text": "Prefers email over calls", "category": "preference"}]},
                      decide=lambda candidate, ids: {"action": "SUPERSEDE", "target_id": phone_fact.id, "reason": "Now prefers email"}))
    await memory.extract_memory(TENANT, {"call_id": session.call_id})
    detail = (await client.get(f"/api/calls/{session.call_id}", headers=H)).json()
    assert len(detail["memory"]["used"]) == 3 and phone_fact.id in {m["id"] for m in detail["memory"]["used"]}
    actions = [e["action"] for e in detail["memory"]["updated"]]
    assert actions.count("superseded") == 1 and actions.count("added") == 2          # the new fact and the episode
    export = (await client.get("/api/members/EVG-482913/memory/export", headers=H)).json()
    statuses = {m["text"]: m["status"] for m in export["memories"]}
    assert statuses[phone_fact.text] == "retired" and statuses["Prefers email over calls"] == "active"
    assert {m["member_ref"] for m in export["memories"]} == {"EVG-482913"}
    assert any(m["source_call_id"] == session.call_id for m in export["memories"])
    assert {e["action"] for e in export["events"]} >= {"added", "superseded"}


# ---------------------------------------------------------------- builder settings
async def test_memory_settings_are_validated_and_defaulted(client, seeded):
    """Covers: DM-07"""
    agent_id = seeded["care"]["agent_id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    for bad in ({"episode_days": 3}, {"remember": "x" * 601}, {"fact_days": 800}):
        r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**cfg, "memory": bad}})
        assert r.status_code == 422, bad
    bare = {k: v for k, v in cfg.items() if k != "memory"}
    saved = (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": bare})).json()["draft_config"]
    assert saved["memory"]["enabled"] is True and saved["memory"]["episode_days"] == 90 and saved["memory"]["fact_days"] == 365
    await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "memory defaults"})
    detail = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()
    assert detail["draft_config"]["memory"]["never_remember"].startswith("Diagnoses")


async def _events(call_id: str):  # noqa: ANN202
    from voiceai.models import CallEvent

    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())
