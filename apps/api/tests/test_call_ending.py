"""How calls end (hand-off, farewell, model goodbye, silence, maximum length) and the caller's feedback.

Spec: /architecture/call-ending-and-feedback.md
Covers: CE-01, CE-02, CE-04, CE-05, CE-06, CE-07, FB-01, FB-02, FB-03, FB-04, FB-05, DM-01
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import LLMTextFrame
from sqlalchemy import func, select

from tests.conftest import script
from voiceai.core.db import sessionmaker
from voiceai.modules.voice.controls import LiveControls
from voiceai.core.llm.gateway import FakeReply
from voiceai.core.tables import Call, CallAnalysis, CallFeedback, Cluster, Escalation, Job
from voiceai.modules.conversation import endings
from voiceai.modules.conversation.session import AgentSession
from voiceai.modules.voice.processors import BrainProcessor
from voiceai.modules.voice.turn_detection import TurnSettings

H = {"X-Tenant-Id": "evergreen-care"}


async def _start(client, seeded, channel: str = "text") -> str:  # noqa: ANN001
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": channel})
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


async def _say(client, call_id: str, text: str) -> dict:  # noqa: ANN001
    r = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


async def _call(call_id: str) -> Call:
    async with sessionmaker()() as s:
        return await s.get(Call, call_id)


# ---------------------------------------------------------------- hand-off, farewell, model goodbye

async def test_handoff_ends_the_call_and_leaves_the_escalation_waiting(client, seeded, fake_llm):
    """Covers: CE-01"""
    fake_llm(script(FakeReply(tool_calls=[("escalate_to_human", {"reason_category": "caller_requested", "reason_detail": "wants a person"})])))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "I want to talk to a person")
    assert out["escalated"] is True and out["ended"] is True and out["call_status"] == "ended"
    call = await _call(call_id)
    assert call.end_reason == "handoff" and call.outcome == "escalated" and call.status == "ended"
    async with sessionmaker()() as s:
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
        assert esc.status == "waiting"
    again = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "hello?"})
    assert again.status_code == 409  # a further turn is not processed


async def test_safety_and_streak_triggers_also_end_the_call(client, seeded, fake_llm):
    """Covers: CE-01"""
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, "I have chest pain")
    assert out["ended"] is True
    assert (await _call(call_id)).end_reason == "handoff"


@pytest.mark.parametrize("text", ["No, that's all, thank you.", "Bye!", "Okay that's all I needed", "Thanks, bye."])
async def test_farewell_phrase_ends_the_call_without_the_model(client, seeded, fake_llm, text):
    """Covers: CE-02"""
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, text)
    assert out["ended"] is True and out["reply"] == endings.GOODBYE
    assert (await _call(call_id)).end_reason == "farewell"


@pytest.mark.parametrize("text", ["Thank you.", "That's all wrong, can you check again?", "So that's it?", "What are my copays?"])
async def test_other_turns_are_not_farewells(client, seeded, fake_llm, text):
    """Covers: CE-02"""
    fake_llm(script(FakeReply(text="Let me look.")))
    call_id = await _start(client, seeded)
    out = await _say(client, call_id, text)
    assert out["ended"] is False and out["reply"] == "Let me look."


async def test_farewell_does_not_end_an_escalated_session(client, seeded, fake_llm):
    """Covers: CE-02, RT-02"""
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    call_id = await _start(client, seeded)
    session = await AgentSession.open(call_id, "evergreen-care")
    await session.escalate("other", "open and escalated")
    reply = await session.reply("bye")
    assert reply.startswith("A specialist will be with you shortly") and not session.state.ended


def test_policy_timer_bounds_are_validated():
    """Covers: CE-07"""
    from pydantic import ValidationError

    from voiceai.modules.agentcfg.domain import Policy

    assert (Policy().silence_reminder_s, Policy().silence_end_s, Policy().max_call_seconds) == (10, 30, 600)
    for bad in ({"silence_reminder_s": 2}, {"silence_end_s": 500}, {"max_call_seconds": 30}, {"silence_reminder_s": 40, "silence_end_s": 40}):
        with pytest.raises(ValidationError):
            Policy(**bad)


async def test_policy_timer_bounds_are_rejected_by_the_api(client, seeded):
    """Covers: CE-07"""
    agent_id = seeded["care"]["agent_id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**cfg, "policy": {**cfg["policy"], "silence_reminder_s": 40, "silence_end_s": 20}}})
    assert r.status_code == 422


# ---------------------------------------------------------------- voice clocks (frame-free: the brain is driven directly)

class _Brain(BrainProcessor):
    RUN_WATCHDOG = False

    def __init__(self, reminder: float = 10, end: float = 30, max_call: float = 600) -> None:
        self.announced: list[str] = []
        self.closed: list[str] = []

        async def announce(text, data=None):  # noqa: ANN001, ANN202
            self.announced.append(text)

        async def start() -> str:
            return "Hello, this is Ava."

        self.session = SimpleNamespace(
            start=start, announce=announce, state=SimpleNamespace(ended=False), end_reason=None,
            config={"policy": {"silence_reminder_s": reminder, "silence_end_s": end, "max_call_seconds": max_call}},
        )
        self.controls = LiveControls(turn=TurnSettings())
        self._task = None
        self._bot_speaking = False
        self._greeted = False
        self._held = []
        self._bot_stopped = asyncio.Event()
        self.pushed: list = []
        self.WELCOME_GRACE_S = 0.01  # type: ignore[misc]

    async def push_frame(self, frame, direction=None) -> None:  # type: ignore[override]  # noqa: ANN001
        self.pushed.append(frame)

    async def _finish(self, reason: str) -> None:  # type: ignore[override]
        self._closing = True
        self.closed.append(reason)

    def spoken(self) -> list[str]:
        return [f.text for f in self.pushed if isinstance(f, LLMTextFrame)]


async def _after_welcome(brain: _Brain) -> float:
    """Run the welcome to its end and return the monotonic time the silence began."""
    await brain.greet()
    brain.on_bot_started()
    await brain.on_bot_stopped()
    await asyncio.sleep(0.05)  # grace period over: the welcome is no longer protected
    assert not brain._welcoming
    return brain._silent_since


async def test_silence_reminder_then_idle_end():
    """Covers: CE-04"""
    brain = _Brain(reminder=10, end=30)
    t0 = await _after_welcome(brain)
    await brain.check_clocks(now=t0 + 5)
    assert brain.announced == []                                        # not silent long enough
    await brain.check_clocks(now=t0 + 11)
    assert brain.announced == [endings.REMINDER_LINE] and brain.closed == []
    brain.on_bot_started()                                              # the reminder plays ...
    await brain.on_bot_stopped()                                        # ... and does not restart the silence
    assert brain._silent_since == t0
    await brain.check_clocks(now=t0 + 15)
    assert brain.announced == [endings.REMINDER_LINE]                   # the reminder is said once
    await brain.check_clocks(now=t0 + 31)
    assert brain.announced[-1] == endings.IDLE_LINE and brain.closed == ["idle"]


async def test_caller_speech_resets_the_silence_clock():
    """Covers: CE-04"""
    brain = _Brain(reminder=10, end=30)
    t0 = await _after_welcome(brain)
    await brain.check_clocks(now=t0 + 11)
    assert brain.announced == [endings.REMINDER_LINE]
    await brain.on_user_started()                                       # the caller answers
    assert brain._silent_since is None
    await brain.check_clocks(now=t0 + 60)                               # nobody is silent while the caller talks
    assert brain.closed == []
    brain.on_bot_started()
    await brain.on_bot_stopped()                                        # the agent's reply is over: a fresh silence
    assert brain._silent_since is not None and not brain._reminded


async def test_no_silence_timers_during_the_welcome():
    """Covers: CE-04"""
    brain = _Brain(reminder=10, end=30)
    await brain.greet()
    assert brain._welcoming
    await brain.check_clocks(now=brain._call_started + 400)             # far beyond the silence limits
    assert brain.announced == [] and brain.closed == []
    brain._end_welcome()


async def test_maximum_duration_ends_the_call():
    """Covers: CE-05"""
    brain = _Brain(max_call=60)
    await _after_welcome(brain)
    await brain.check_clocks(now=brain._call_started + 61)
    assert brain.announced == [endings.MAX_DURATION_LINE] and brain.closed == ["max_duration"]
    assert endings.MAX_DURATION_LINE in brain.spoken()


async def test_a_closing_call_is_not_interrupted():
    """Covers: CE-06"""
    brain = _Brain()
    await _after_welcome(brain)
    brain._closing = True
    brain._bot_speaking = True
    interrupted: list[int] = []

    async def broadcast() -> None:
        interrupted.append(1)

    brain.broadcast_interruption = broadcast  # type: ignore[method-assign]
    await brain.on_user_started()
    await brain.on_user_turn("anything")
    assert interrupted == [] and brain._task is None


async def test_end_reason_is_reported_after_the_closing_speech(app, database, seeded, fake_llm):
    """Covers: CE-06"""
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    session = await AgentSession.open((await _make_call(seeded)), "evergreen-care")
    parts = [c async for c in session.respond("goodbye")]
    assert parts == [endings.GOODBYE] and session.state.ended and session.end_reason == "farewell"


async def _make_call(seeded) -> str:  # noqa: ANN001
    from voiceai.modules.conversation.session import create_call

    async with sessionmaker()() as s:
        call = await create_call(s, "evergreen-care", seeded["care"]["agent_id"], "voice")
        await s.commit()
        return call.id


# ---------------------------------------------------------------- feedback

async def _ended_call(client, seeded, fake_llm) -> str:  # noqa: ANN001
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    call_id = await _start(client, seeded)
    await _say(client, call_id, "no, that's all")
    return call_id


async def test_feedback_is_stored_shown_and_replaceable(client, seeded, fake_llm):
    """Covers: FB-01"""
    call_id = await _ended_call(client, seeded, fake_llm)
    r = await client.post(f"/api/calls/{call_id}/feedback", headers=H, json={"rating": "down", "comment": "It never told me the grace period"})
    assert r.status_code == 200 and r.json() == {"rating": "down", "comment": "It never told me the grace period"}
    detail = (await client.get(f"/api/calls/{call_id}", headers=H)).json()
    assert detail["feedback"]["rating"] == "down" and detail["feedback"]["comment"].startswith("It never told")
    summary = next(c for c in (await client.get("/api/calls", headers=H)).json()["items"] if c["id"] == call_id)
    assert summary["feedback"] == "down"
    await client.post(f"/api/calls/{call_id}/feedback", headers=H, json={"rating": "up"})
    assert (await client.get(f"/api/calls/{call_id}", headers=H)).json()["feedback"]["rating"] == "up"
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(CallFeedback).where(CallFeedback.call_id == call_id)) == 1


async def test_feedback_validation_and_states(client, seeded, fake_llm):
    """Covers: FB-02"""
    fake_llm(script())
    running = await _start(client, seeded)
    r = await client.post(f"/api/calls/{running}/feedback", headers=H, json={"rating": "up"})
    assert r.status_code == 409 and r.json()["error"] == "call_active"
    assert (await client.post("/api/calls/nope/feedback", headers=H, json={"rating": "up"})).status_code == 404
    await client.post(f"/api/calls/{running}/end", headers=H)
    assert (await client.post(f"/api/calls/{running}/feedback", headers=H, json={"rating": "meh"})).status_code == 422
    assert (await client.post(f"/api/calls/{running}/feedback", headers=H, json={"rating": "up", "comment": "x" * 301})).status_code == 422
    async with sessionmaker()() as s:  # a simulation call cannot be rated
        call = await s.get(Call, running)
        call.is_eval = True
        await s.commit()
    r = await client.post(f"/api/calls/{running}/feedback", headers=H, json={"rating": "up"})
    assert r.status_code == 409 and r.json()["error"] == "not_ratable"


async def _jobs(call_id: str) -> int:
    async with sessionmaker()() as s:
        return await s.scalar(select(func.count()).select_from(Job).where(Job.kind == "analyze_call", Job.payload["call_id"].as_string() == call_id))


async def test_thumbs_down_queues_one_more_analysis_and_it_sees_the_feedback(client, seeded, fake_llm):
    """Covers: FB-03"""
    call_id = await _ended_call(client, seeded, fake_llm)
    before = await _jobs(call_id)
    await client.post(f"/api/calls/{call_id}/feedback", headers=H, json={"rating": "up"})
    assert await _jobs(call_id) == before                               # thumbs up queues nothing
    await client.post(f"/api/calls/{call_id}/feedback", headers=H, json={"rating": "down", "comment": "Too slow"})
    await client.post(f"/api/calls/{call_id}/feedback", headers=H, json={"rating": "down", "comment": "Too slow, again"})
    assert await _jobs(call_id) == before + 1                           # once, however often it is sent

    seen: list[str] = []

    def analysis(role, messages, tools):  # noqa: ANN001, ANN202
        seen.append(messages[0]["content"])
        return {"outcome": "resolved", "intent": "policy_status", "root_cause": "none", "gap_summary": "", "caller_goal": "Check a policy",
                "resolution_summary": "Answered", "sentiment_start": "neutral", "sentiment_end": "neutral"}

    fake_llm(analysis)
    from voiceai.modules.learning.analyze import analyze_call

    await analyze_call("evergreen-care", {"call_id": call_id})
    assert "Caller feedback after the call: thumbs down: Too slow, again" in seen[0]
    async with sessionmaker()() as s:
        a = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
        assert a.outcome == "resolved" and a.root_cause != "none" and a.gap_summary.strip()  # never "none" or empty for a thumbs down


async def test_thumbs_down_resolved_call_joins_a_cluster_and_counts_toward_readiness(client, seeded, fake_llm):
    """Covers: FB-04"""
    from voiceai.modules.learning.analyze import analyze_call

    fake_llm(lambda role, m, t: {"outcome": "resolved", "intent": "payment_status", "root_cause": "missing_knowledge",
                                   "gap_summary": "Explaining the grace period on an overdue payment", "caller_goal": "Ask about an overdue payment",
                                   "resolution_summary": "Explained", "sentiment_start": "neutral", "sentiment_end": "frustrated"})
    before = (await client.get("/api/dashboard/summary", headers=H)).json()
    ids = []
    for _ in range(5):
        call_id = await _start(client, seeded)
        await client.post(f"/api/calls/{call_id}/end", headers=H)
        await client.post(f"/api/calls/{call_id}/feedback", headers=H, json={"rating": "down", "comment": "Did not explain the grace period"})
        await analyze_call("evergreen-care", {"call_id": call_id})
        ids.append(call_id)
    async with sessionmaker()() as s:
        analyses = list((await s.scalars(select(CallAnalysis).where(CallAnalysis.call_id.in_(ids)))).all())
        assert all(a.outcome == "resolved" and a.cluster_id for a in analyses)
        cluster_id = analyses[0].cluster_id
        assert {a.cluster_id for a in analyses} == {cluster_id}
    out = (await client.get(f"/api/insights/clusters/{cluster_id}", headers=H)).json()
    assert out["dislike_count"] == 5 and out["signal_count"] == 5 and out["escalations_28d"] == 0
    assert out["ready_for_fix"] is True                                 # fixable, 5 signals, no escalations
    assert {c["feedback"]["rating"] for c in out["calls"]} == {"down"}
    after = (await client.get("/api/dashboard/summary", headers=H)).json()
    assert after["by_root_cause"] == before["by_root_cause"]            # the escalation root-cause chart counts escalations only
    assert after["totals"]["escalated"] == before["totals"]["escalated"]                    # a thumbs down does not change the outcome ...
    assert after["totals"]["resolved"] == before["totals"]["resolved"] + 5                  # ... the five calls still count as contained
    async with sessionmaker()() as s:  # the cluster is not a dashboard "escalation": no escalated analysis in it
        assert await s.scalar(select(func.count()).select_from(CallAnalysis).where(CallAnalysis.cluster_id == cluster_id, CallAnalysis.outcome == "escalated")) == 0
        assert (await s.get(Cluster, cluster_id)).escalation_count == 0


async def test_calls_can_be_filtered_by_feedback(client, seeded, fake_llm):
    """Covers: FB-05"""
    down = await _ended_call(client, seeded, fake_llm)
    up = await _ended_call(client, seeded, fake_llm)
    none = await _ended_call(client, seeded, fake_llm)
    await client.post(f"/api/calls/{down}/feedback", headers=H, json={"rating": "down"})
    await client.post(f"/api/calls/{up}/feedback", headers=H, json={"rating": "up"})

    async def ids(flt: str) -> set[str]:
        items = (await client.get(f"/api/calls?feedback={flt}", headers=H)).json()["items"]
        return {c["id"] for c in items}

    assert down in await ids("down") and up not in await ids("down") and none not in await ids("down")
    assert up in await ids("up") and down not in await ids("up")
    assert none in await ids("none") and down not in await ids("none") and up not in await ids("none")
    assert (await client.get("/api/calls?feedback=sideways", headers=H)).status_code == 422


async def test_existing_database_gets_the_feedback_table(client, seeded):
    """Covers: DM-01"""
    from sqlalchemy import inspect

    from voiceai.core import db

    async with db.engine().begin() as conn:  # an older database that predates the table
        await conn.run_sync(lambda c: CallFeedback.__table__.drop(c))
    async with db.engine().connect() as conn:
        assert "call_feedback" not in await conn.run_sync(lambda c: inspect(c).get_table_names())
    await db.init_db()                                                  # what the app does at start-up
    async with db.engine().connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert "call_feedback" in tables and "calls" in tables
    async with sessionmaker()() as s:                                   # existing rows are untouched
        assert await s.scalar(select(func.count()).select_from(Call)) > 0
