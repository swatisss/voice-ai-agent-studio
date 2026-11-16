"""CP-0048: a request for a person escalates at once (front desk and agents); the prompt rules for pounds and third parties.

Typed conversations on the fake LLM, modelled on the live QA of 2026-11-16.

Covers: ES-13, RTE-23
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from tests.test_front_desk_safety import _desk, _open, ready  # noqa: F401
from tests.test_runtime import _say, _start
from voiceai.db import sessionmaker
from voiceai.models import Call, Conversation, Escalation
from voiceai.routing import catalog
from voiceai.runtime import escalation
from tests.conftest import script
from voiceai.llm.gateway import FakeReply

PROMPT = (Path(__file__).resolve().parents[3] / "specs" / "prompts" / "agent-system-prompt.md").read_text(encoding="utf-8")

ASKS = [
    "I want to speak to a human", "agent please", "get me a manager right now", "Can I talk to someone real? This bot is useless",
    "put me through to a representative", "human please", "I need a real person", "Speak to an agent", "Human", "talk to a person about my claim",
    "I'd like to speak to a colleague", "Please connect me with a supervisor", "I’d like to talk to a live agent",
]
NOT_ASKS = [
    "Can I talk to someone about adding my baby?", "My aunt, a person I care for, died last week.", "I spoke to a human last week and she said it was fine.",
    "The agent said to call back.", "Can you check my claim please", "I need my manager's policy number", "Who is the manager of the scheme?",
    "I want to add a person to my policy", "talk me through the excess", "Hi, I'd like a quote",
]


@pytest.mark.parametrize("line", ASKS)
def test_these_lines_ask_for_a_person(line):
    """Covers: ES-13"""
    assert escalation.person_match(line), line


@pytest.mark.parametrize("line", NOT_ASKS)
def test_these_lines_do_not(line):
    """Covers: ES-13"""
    assert not escalation.person_match(line), line


async def test_an_agent_escalates_without_asking_the_model(client, seeded, fake_llm):  # noqa: ANN001
    """Covers: ES-13"""
    fake_llm(script(FakeReply(text="the model must not answer a request for a person")))
    out = await _say(client, await _start(client, seeded), "I want to speak to a human")
    assert out["escalated"] is True and "colleague" in out["reply"] or "specialist" in out["reply"]
    async with sessionmaker()() as s:
        esc = (await s.scalars(select(Escalation).order_by(Escalation.created_at.desc()))).first()
    assert esc.reason_category == "caller_requested" and "person" in esc.reason_detail


async def test_the_front_desk_does_not_clarify_a_request_for_a_person(client, ready, monkeypatch):  # noqa: ANN001, F811
    """Covers: RTE-23"""
    seeded, brain = ready
    care = seeded["care"]["agent_id"]
    await _desk(default_agents={"member": care}, routing_mode="decision_model")

    async def no_stage_a(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("no routing for a request for a person")

    monkeypatch.setattr(catalog, "stage_a", no_stage_a)
    out = await _open(client, "agent please")
    assert out["agent"]["id"] == care
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, out["conversation_id"])
        seg = await s.get(Call, conv.current_call_id)
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == seg.id))
    assert conv.routing[-1]["method"] == "person_request" and conv.clarifications == 0
    assert esc is not None and esc.reason_category == "caller_requested" and seg.end_reason == "handoff"
    assert brain.calls.get("realtime", 0) == 0 and brain.calls.get("router", 0) == 0


def test_the_prompt_speaks_pounds_and_guards_third_parties():
    """Covers: ES-13"""
    assert 'like "£650"' in PROMPT and "never $" in PROMPT
    assert "calling about someone else's policy" in PROMPT and "do not verify with that person's number" in PROMPT
    assert "$650" not in PROMPT
