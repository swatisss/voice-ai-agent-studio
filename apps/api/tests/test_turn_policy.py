"""The AgentSession turn policy: events in, decisions out, for channels whose model speaks for itself.

Covers: RT-11, RT-12, RT-13, RT-14, RT-15
"""
from __future__ import annotations

import json

from sqlalchemy import select

from tests.conftest import script
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply, Usage
from voiceai.models import CallEvent, Escalation
from voiceai.runtime import endings, escalation
from voiceai.runtime.session import GOODBYE, HANDOFF_DEFAULT, AgentSession, create_call

TENANT = "evergreen-care"
VERIFY = ("verify_member", {"member_id": "482913", "date_of_birth": "1986-04-12"})
CLAIM = ("get_claim_status", {"claim_id": "C-20931"})


async def open_session(seeded, channel: str = "voice", agent: str = "care") -> AgentSession:
    async with sessionmaker()() as s:
        call = await create_call(s, TENANT, seeded[agent]["agent_id"], channel)
        await s.commit()
    session = await AgentSession.open(call.id, TENANT)
    await session.start()
    return session


async def stored(session: AgentSession) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == session.call_id).order_by(CallEvent.seq))).all())


async def escalations(session: AgentSession) -> list[Escalation]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(Escalation).where(Escalation.call_id == session.call_id))).all())


def no_model(role, messages, tools):  # noqa: ANN001, ANN201
    raise AssertionError("the turn policy must not call a model")


async def test_caller_turn_rules(client, seeded, fake_llm):
    """Covers: RT-11"""
    fake_llm(no_model)
    session = await open_session(seeded)
    assert (await session.caller_turn("What does my plan cover?")).model_turn

    farewell = await session.commit(await session.caller_turn("No, that's all, thank you."))
    assert (farewell.say, farewell.end) == (GOODBYE, "farewell")

    safety = await session.commit(await (await open_session(seeded)).caller_turn("I have chest pain"))
    assert (safety.say, safety.end) == (escalation.SAFETY_MESSAGE, "handoff")

    held = await open_session(seeded)
    await held.escalate("other", "test")
    holding = await held.commit(await held.caller_turn("Hello?"))
    assert holding.say == held.config["policy"].get("holding_message", "A specialist will be with you shortly.") and holding.end is None
    assert (await stored(held))[-1].text == holding.say


async def test_a_caller_turn_line_is_recorded_on_commit(client, seeded, fake_llm):
    """Covers: RT-11 (a model reply cut off for the line is stored before it)"""
    fake_llm(no_model)
    session = await open_session(seeded)
    decision = await session.caller_turn("No, that's all, thank you.")
    await session.reply_finished("Let me look that up", interrupted=True, decide=False)
    await session.commit(decision)
    await session.commit(decision)  # idempotent
    assistant = [e.text for e in await stored(session) if e.kind == "assistant"]
    assert assistant[-2:] == ["Let me look that up [interrupted]", GOODBYE]


async def test_tool_rounds_and_refresh(client, seeded, fake_llm):
    """Covers: RT-12"""
    fake_llm(no_model)
    session = await open_session(seeded)
    await session.caller_turn("Check claim C-20931")
    blocked = await session.tool_requested(*CLAIM)
    assert "identity_not_verified" in blocked.output and not blocked.refresh
    verified = await session.tool_requested(*VERIFY)
    assert verified.refresh and session.state.verified_member_ref == "EVG-482913"
    await session.tool_requested(*CLAIM)
    await session.tool_requested(*CLAIM)
    calls_before = sum(1 for e in await stored(session) if e.kind == "tool_call")
    fifth = await session.tool_requested(*CLAIM)
    assert json.loads(fifth.output) == {"error": "tool_round_limit"}
    assert sum(1 for e in await stored(session) if e.kind == "tool_call") == calls_before  # not run
    await session.caller_turn("And the other one?")  # the count restarts
    assert "error" not in json.loads((await session.tool_requested(*CLAIM)).output)


async def test_post_turn_trigger_hands_off(client, seeded, fake_llm):
    """Covers: RT-13"""
    fake_llm(no_model)
    session = await open_session(seeded)
    session.config["policy"]["max_turns"] = 1
    session.config["policy"].pop("handoff_message", None)
    await session.caller_turn("What does my plan cover?")
    decision = await session.reply_finished("It covers a lot.", latency_ms=300)
    assert (decision.say, decision.end) == (HANDOFF_DEFAULT, "handoff")
    assert len(await escalations(session)) == 1
    assert (await session.reply_finished("again")).say is None and len(await escalations(session)) == 1


async def test_goodbye_after_end_call_only_when_silent(client, seeded, fake_llm):
    """Covers: RT-14"""
    fake_llm(no_model)
    silent = await open_session(seeded)
    await silent.caller_turn("thanks")
    silent.state.end_requested = True
    decision = await silent.reply_finished("")
    assert (decision.say, decision.end) == (endings.GOODBYE, "end_call")

    spoke = await open_session(seeded)
    await spoke.caller_turn("thanks")
    spoke.state.end_requested = True
    decision = await spoke.reply_finished("Glad I could help, goodbye!")
    assert (decision.say, decision.end) == (None, "end_call")


ROUND = Usage(input_tokens=100, output_tokens=20)  # what the fake model reports for each round, as a realtime service does per response
MEASURED = {"latency_ms", "duration_ms", "tool_call_id", "escalation_id"}  # timings and generated ids differ by run


def shape(events: list[CallEvent]) -> list[tuple]:
    """Each stored event with its data, apart from timestamps, measured latencies and generated ids (RT-15)."""
    return [(e.kind, e.text, {k: v for k, v in (e.data or {}).items() if k not in MEASURED}) for e in events]


def state_of(session: AgentSession) -> tuple:
    st = session.state
    return (st.turns, st.verified_member_ref, st.escalated, st.ended, st.end_requested, [t.get("name") for t in st.tools_used],
            st.tokens_in, st.tokens_out, session.end_reason)


async def test_text_loop_and_policy_events_match(client, seeded, fake_llm):
    """Covers: RT-15"""
    fake_llm(script(FakeReply(tool_calls=[CLAIM]), FakeReply(tool_calls=[VERIFY]), FakeReply(tool_calls=[CLAIM]), FakeReply(text="Paid.")))
    loop = await open_session(seeded, channel="text")
    await loop.reply("What about claim C-20931?")

    fake_llm(no_model)
    driven = await open_session(seeded, channel="text")
    await driven.caller_turn("What about claim C-20931?")
    for name, args in (CLAIM, VERIFY, CLAIM):
        await driven.tool_requested(name, args)
        await driven.reply_finished("", usage=ROUND, decide=False)
    await driven.reply_finished("Paid.", usage=ROUND)

    assert shape(await stored(loop)) == shape(await stored(driven))
    assert state_of(loop) == state_of(driven)
    assert len(await escalations(loop)) == len(await escalations(driven)) == 0


async def test_text_loop_and_policy_match_on_a_model_handoff(client, seeded, fake_llm):
    """Covers: RT-15"""
    handoff = ("escalate_to_human", {"reason_category": "policy_required", "reason_detail": "Caller wants to appeal"})
    fake_llm(script(FakeReply(text="Let me get someone. ", tool_calls=[handoff])))
    loop = await open_session(seeded, channel="text")
    reply = await loop.reply("I want to appeal this decision")

    fake_llm(no_model)
    driven = await open_session(seeded, channel="text")
    await driven.caller_turn("I want to appeal this decision")
    await driven.tool_requested(*handoff)
    await driven.reply_finished("Let me get someone. ", usage=ROUND, decide=False)
    await driven.commit(decision := await driven.tools_finished(spoke=True))
    await driven.end(decision.end)

    assert reply.endswith(loop.config["policy"]["handoff_message"]) and loop.end_reason == "handoff"
    assert shape(await stored(loop)) == shape(await stored(driven))
    assert state_of(loop) == state_of(driven)
    assert len(await escalations(loop)) == len(await escalations(driven)) == 1


async def test_text_loop_and_policy_match_on_a_silent_end_call(client, seeded, fake_llm):
    """Covers: RT-15"""
    end_call = ("end_call", {"summary": "Answered the coverage question"})
    fake_llm(script(FakeReply(tool_calls=[end_call]), FakeReply(text="")))
    loop = await open_session(seeded, channel="text")
    assert await loop.reply("That answers it") == GOODBYE

    fake_llm(no_model)
    driven = await open_session(seeded, channel="text")
    await driven.caller_turn("That answers it")
    await driven.tool_requested(*end_call)
    await driven.reply_finished("", usage=ROUND, decide=False)
    await driven.reply_finished("", usage=ROUND, decide=False)  # the model's second round said nothing
    await driven.commit(decision := await driven.tools_finished(spoke=False))
    await driven.end(decision.end)

    assert loop.end_reason == driven.end_reason == "end_call"
    assert shape(await stored(loop)) == shape(await stored(driven))
    assert state_of(loop) == state_of(driven)
