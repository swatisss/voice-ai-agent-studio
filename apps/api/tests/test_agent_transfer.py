"""Agent-to-agent transfer: segments, carry-over, the tool's availability, limits, voice, scoring, dashboard, learning.

Covers: XFR-01, XFR-02, XFR-03, XFR-04, XFR-05, XFR-06, XFR-07, XFR-08, RT-16, TS-10, ES-10, SC-13, SL-13, IDV-08
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from tests.test_capability_catalog import run_index_jobs
from tests.test_supervisor_routing import Brain
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent, CallScorecard, Conversation, Escalation, FixProposal
from voiceai.routing import catalog
from voiceai.runtime.session import REGISTRY, AgentSession

H = {"X-Tenant-Id": "northgate-health"}
VERIFY_SARAH = ("verify_member", {"member_id": "410237", "date_of_birth": "1984-03-14"})
TRANSFER = ("transfer_to_agent", {"reason": "Wants to know what the plan covers for dental", "summary": "Verified member asking about dental cover"})
DENTAL = "What does my plan cover for dental?"


class Script(Brain):
    """Realtime replies in order (FakeReply or text)."""

    def __init__(self, *replies) -> None:  # noqa: ANN002
        super().__init__()
        self.queue = list(replies)

    def __call__(self, role, messages, tools):  # noqa: ANN001, ANN204
        if role == "realtime":
            self.calls["realtime"] = self.calls.get("realtime", 0) + 1
            self.last_tools = [t["function"]["name"] for t in tools or []]
            self.last_system = messages[0]["content"]
            reply = self.queue.pop(0) if self.queue else "Okay."
            return reply if isinstance(reply, FakeReply) else FakeReply(text=reply)
        return super().__call__(role, messages, tools)


@pytest.fixture
async def setup(client, seeded, fake_llm, monkeypatch):  # noqa: ANN001
    brain = Brain()
    fake_llm(brain)
    await run_index_jobs()
    care, claims = seeded["care"]["agent_id"], seeded["claims"]["agent_id"]

    async def to_care(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
        """Claims for 'pre-authorisation', Customer Care for everything else (when they are candidates)."""
        pool = set(candidates or set())
        best = claims if "pre-authorisation" in text and claims in pool else care
        return [{"agent_id": best, "score": 0.95}, *[{"agent_id": a, "score": 0.2} for a in pool if a != best]]

    monkeypatch.setattr(catalog, "stage_a", to_care)
    return seeded


async def start(client, agent_id: str) -> str:  # noqa: ANN001
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member", "agent_id": agent_id})
    assert r.status_code == 201, r.text
    return r.json()["conversation_id"]


async def say(client, cid: str, text: str) -> dict:  # noqa: ANN001
    r = await client.post(f"/api/conversations/{cid}/messages", headers=H, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


async def test_transfer_to_the_right_agent_keeps_verification(client, setup, fake_llm):
    """Covers: XFR-01, XFR-02, RT-16, IDV-08"""
    brain = Script(FakeReply(tool_calls=[VERIFY_SARAH]), "Thanks Sarah, you're verified.",
                   FakeReply(tool_calls=[TRANSFER]), "Your plan includes one dental check-up a year and a £300 dental allowance.")
    fake_llm(brain)
    cid = await start(client, setup["claims"]["agent_id"])
    await say(client, cid, "My membership number is 410237 and my date of birth is 14 March 1984.")
    turn = await say(client, cid, DENTAL)
    assert turn["transferred"] is True and turn["agent"]["name"] == "Customer Care"
    texts = [m["text"] for m in turn["messages"]]
    assert texts[0] == "You're now with our member services team." and "dental allowance" in texts[-1]
    async with sessionmaker()() as s:
        first, second = (await s.scalars(select(Call).where(Call.conversation_id == cid).order_by(Call.segment))).all()
        assert (first.end_reason, first.outcome) == ("transfer", "transferred")
        assert second.routed_by == "transfer" and second.segment == 2 and second.caller_ref == "NGH-410237"
        assert second.meta["handoff"]["reason"].startswith("Wants to know") and second.meta["state"]["verified"] is True
        notes = (await s.scalars(select(CallEvent.text).where(CallEvent.call_id == first.id, CallEvent.kind == "system"))).all()
        assert any(n.startswith("Transferred: Wants to know") for n in notes)
        user_lines = (await s.scalars(select(CallEvent.text).where(CallEvent.call_id == second.id, CallEvent.kind == "user"))).all()
        assert user_lines == [DENTAL]
    # the receiving agent's prompt carries the handoff; it does not ask to verify again; its history holds the last lines
    assert "Wants to know what the plan covers for dental" in brain.last_system and "Verified member asking" in brain.last_system
    session = await AgentSession.open(second.id, "northgate-health")
    assert session.state.verified and session.state.verification_level == first.meta["state"]["verification_level"]
    assert any("verified" in (m.get("content") or "") for m in session.history if m["role"] == "assistant")


async def test_tool_only_inside_conversations(client, setup, fake_llm):
    """Covers: XFR-03, TS-10"""
    brain = Script("Hello.", "Hello.")
    fake_llm(brain)
    r = await client.post("/api/calls", headers=H, json={"agent_id": setup["claims"]["agent_id"], "channel": "text"})
    await client.post(f"/api/calls/{r.json()['call_id']}/messages", headers=H, json={"text": "hi"})
    assert "transfer_to_agent" not in brain.last_tools
    cid = await start(client, setup["claims"]["agent_id"])
    await say(client, cid, "hi")
    assert "transfer_to_agent" in brain.last_tools and "Other teams" in brain.last_system
    tool = {"name": "transfer_to_agent", "method": "GET", "url": "/x", "parameters": {"type": "object", "properties": {}}}
    assert (await client.post("/api/tools", headers=H, json=tool)).status_code == 422


async def test_limit_and_no_candidate_escalate(client, setup, fake_llm, monkeypatch):
    """Covers: XFR-04, ES-10"""
    fake_llm(Script(FakeReply(tool_calls=[TRANSFER])))
    cid = await start(client, setup["claims"]["agent_id"])
    async with sessionmaker()() as s:
        await s.execute(update(Conversation).where(Conversation.id == cid).values(transfer_count=3))
        await s.commit()
    turn = await say(client, cid, DENTAL)
    assert turn["status"] in ("escalated", "ended") and turn["escalation"] is not None
    async with sessionmaker()() as s:
        esc = await s.scalar(select(Escalation).join(Call, Call.id == Escalation.call_id).where(Call.conversation_id == cid))
        call = await s.scalar(select(Call).where(Call.conversation_id == cid))
    assert esc.reason_category == "transfer_failed" and call.end_reason == "handoff"
    # no other candidate: an internal assistant (the seed has none, so the test adds one) is alone in the staff scope
    r = await client.post("/api/agents", headers=H, json={"name": "Staff Helpdesk", "draft_config": {"mode": "internal", "voice": {"pipeline": "cascade"}}})
    assert r.status_code == 200, r.text
    internal = r.json()["id"]
    assert (await client.post(f"/api/agents/{internal}/publish", headers=H, json={})).status_code == 200
    fake_llm(Script(FakeReply(tool_calls=[TRANSFER])))
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "staff", "agent_id": internal})
    turn = await say(client, r.json()["conversation_id"], "something else")
    assert turn["escalation"] is None or turn["status"] != "active"


async def test_requester_is_excluded(client, setup, fake_llm):
    """Covers: XFR-05"""
    fake_llm(Script(FakeReply(tool_calls=[TRANSFER]), "Sure."))
    cid = await start(client, setup["claims"]["agent_id"])
    await say(client, cid, DENTAL)
    view = (await client.get(f"/api/conversations/{cid}", headers=H)).json()
    decision = view["routing"][-1]
    assert decision["trigger"] == "transfer" and setup["claims"]["agent_id"] in decision["excluded"]
    assert decision["agent_id"] != setup["claims"]["agent_id"]


async def test_voice_transfer_keeps_socket_voice_and_pipeline(client, setup, fake_llm, monkeypatch, app):
    """Covers: XFR-06"""
    from voiceai.routing.voice_session import ConversationSession

    for k, v in {"PUBLIC_API_SECRET": "s3cret", "OPENAI_API_KEY": "sk-test", "DEEPGRAM_API_KEY": "dg"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    claims = setup["claims"]["agent_id"]  # put the first agent on the realtime pipeline; Customer Care stays on cascade
    cfg = (await client.get(f"/api/agents/{claims}", headers=H)).json()["draft_config"]
    cfg["voice"]["pipeline"] = "realtime"
    assert (await client.put(f"/api/agents/{claims}", headers=H, json={"draft_config": cfg})).status_code == 200
    assert (await client.post(f"/api/agents/{claims}/publish", headers=H, json={})).status_code == 200
    fake_llm(Script())
    r = await client.post("/api/conversations", headers=H, json={"channel": "voice", "scope": "member", "agent_id": claims})
    assert r.status_code == 201, r.text
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, r.json()["conversation_id"])
    session = await ConversationSession.open(conv, app)
    pipeline, rt_voice = session.call_settings.pipeline, (session.config.get("voice") or {}).get("realtime")
    assert pipeline == "realtime"
    first = session.agent
    await first.caller_turn(DENTAL)
    first.state.transfer_requested = {"reason": "dental cover", "summary": "asks about dental"}
    decision = await session.tools_finished(spoke=False)
    assert decision.say == "You're now with our member services team." and decision.model_turn and decision.refresh
    assert session.agent is not first and session.agent.agent_id == setup["care"]["agent_id"]
    assert session.call_settings.pipeline == pipeline and (session.config.get("voice") or {}).get("realtime") == rt_voice
    assert "member care" not in session.prompt().lower() or "How this caller reached you" in session.prompt()


async def test_early_transfer_is_scored(client, setup, fake_llm):
    """Covers: XFR-07, SC-13"""
    from voiceai.learning import scoring

    fake_llm(Script(FakeReply(tool_calls=[TRANSFER]), "Sure."))
    cid = await start(client, setup["claims"]["agent_id"])
    await say(client, cid, DENTAL)
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member", "message": "I need a pre-authorisation for a knee scan."})
    routed_cid = r.json()["conversation_id"]
    fake_llm(Script(FakeReply(tool_calls=[TRANSFER]), "Sure."))
    await say(client, routed_cid, DENTAL)
    direct = await client.post("/api/calls", headers=H, json={"agent_id": setup["care"]["agent_id"], "channel": "text"})
    async with sessionmaker()() as s:
        routed_first = await s.scalar(select(Call).where(Call.conversation_id == routed_cid, Call.segment == 1))
        transferred_in = await s.scalar(select(Call).where(Call.conversation_id == cid, Call.segment == 2))
        direct_call = await s.get(Call, direct.json()["call_id"])
        direct_call.ended_at = utcnow()
        await s.commit()
    judge = lambda role, m, t: {"outcome": "resolved", "checks": {}, "reason": ""} if role == "judge" else Script()(role, m, t)  # noqa: E731
    fake_llm(judge)
    async with sessionmaker()() as s:
        card = await scoring.score(s, await s.get(Call, routed_first.id), always_judge=True)
        verdicts = {c["key"]: c["verdict"] for c in card.checks}
        assert verdicts["routing.early_transfer"] == "fail" and "routing.in_scope" in verdicts
        card2 = await scoring.score(s, await s.get(Call, direct_call.id))
        v2 = {c["key"]: c["verdict"] for c in card2.checks}
        assert v2["routing.early_transfer"] == "n/a" and v2["routing.in_scope"] == "n/a"
        assert (await scoring.score(s, await s.get(Call, transferred_in.id))) is not None
        await s.commit()


async def test_dashboard_counts_a_conversation_once(client, setup, fake_llm):
    """Covers: XFR-08"""
    before = (await client.get("/api/dashboard/summary", headers=H)).json()["totals"]["calls"]
    fake_llm(Script(FakeReply(tool_calls=[TRANSFER]), "Sure."))
    cid = await start(client, setup["claims"]["agent_id"])
    await say(client, cid, DENTAL)
    await client.post(f"/api/conversations/{cid}/end", headers=H)
    after = (await client.get("/api/dashboard/summary", headers=H)).json()["totals"]["calls"]
    assert after == before + 1
    calls = (await client.get(f"/api/calls?conversation_id={cid}", headers=H)).json()["items"]
    assert sorted(c["segment"] for c in calls) == [1, 2] and all(c["conversation_id"] == cid for c in calls)
    summary = (await client.get("/api/routing/summary?days=7", headers=H)).json()
    assert summary["decisions"] >= 1 and "misroute_rate" in summary and summary["transfers_per_conversation"] is not None


async def test_misroutes_become_a_routing_proposal(client, setup, fake_llm):
    """Covers: SL-13"""
    from voiceai.routing import learning

    claims, care = setup["claims"]["agent_id"], setup["care"]["agent_id"]
    for i in range(3):
        r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member", "message": "I need a pre-authorisation for a knee scan."})
        cid = r.json()["conversation_id"]
        fake_llm(Script(FakeReply(tool_calls=[TRANSFER]), "Sure."))
        await say(client, cid, f"how much dental allowance do I have left {i}")
        async with sessionmaker()() as s:
            first = await s.scalar(select(Call).where(Call.conversation_id == cid, Call.segment == 1))
            assert first.agent_id == claims and first.end_reason == "transfer"
            s.add(CallScorecard(tenant_id="northgate-health", call_id=first.id, agent_id=claims, agent_version_id=first.agent_version_id,
                                measures={}, checks=[{"key": "routing.early_transfer", "verdict": "fail"}], hard_fail=False, score=0.5, judged=False))
            await s.commit()
    before = (await client.get(f"/api/agents/{care}/capability", headers=H)).json()
    report = await learning.draft_proposals("northgate-health", utcnow() - timedelta(days=1))
    assert report["misrouted"] == 3 and report["drafted"] == 1
    async with sessionmaker()() as s:
        p = await s.scalar(select(FixProposal).where(FixProposal.kind == "routing_update"))
    assert p.agent_id == care and p.status == "ready" and len(p.payload["add_utterances"]) == 3 and p.latest_eval_run_id
    assert (await client.get(f"/api/agents/{care}/capability", headers=H)).json() == before  # nothing changes until approved
    REGISTRY.clear()
