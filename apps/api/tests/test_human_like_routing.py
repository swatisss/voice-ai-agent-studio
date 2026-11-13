"""Human-like routed conversations (CP-0041): the leader after a clarification, the front desk's handoff, the Handoff block.

Typed (text) conversations on the fake LLM, modelled on the owner's call of 2026-11-13: a shoulder operation, "Yes.".

Covers: RTE-18, RTE-19, RTE-20, XFR-09
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.test_supervisor_routing import H, Brain, brain, indexed  # noqa: F401  (fixtures)
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, Conversation
from voiceai.routing import catalog, front_desk, supervisor
from voiceai.runtime import prompt as prompt_mod

ASK = "I'm waiting to hear if my shoulder operation has been approved."
QUESTION = "Are you asking about getting your shoulder surgery approved, checking the status of a pre-authorisation, or something else?"


class Recorder(Brain):
    """The test Brain, also keeping every realtime request so a test can read the agent's prompt and history."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[list[dict[str, Any]]] = []

    def __call__(self, role: str, messages: list[dict[str, Any]], tools: Any) -> Any:  # noqa: ANN401
        if role == "realtime":
            self.requests.append(messages)
            return FakeReply(text=self.realtime.pop(0) if self.realtime else "Happy to help with that.")
        return super().__call__(role, messages, tools)


@pytest.fixture
def rec(fake_llm) -> Recorder:  # noqa: ANN001
    r = Recorder()
    fake_llm(r)
    return r


def two_rounds(first: list[dict[str, Any]], second: list[dict[str, Any]]):  # noqa: ANN201
    """Stage A that ranks `first` before the clarifying question and `second` after it."""
    calls = {"n": 0}

    async def fake(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
        calls["n"] += 1
        return first if calls["n"] == 1 else second

    return fake


async def _desk(care: str) -> None:
    async with sessionmaker()() as s:
        await front_desk.update(s, "northgate-health", front_desk.FrontDeskPatch(default_agents={"member": care}, max_clarifications=1))
        await s.commit()


async def _ask_then_answer(client, rec: Recorder, answer: str) -> tuple[str, dict[str, Any]]:  # noqa: ANN001
    rec.router.append({"question": QUESTION})
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member", "message": ASK})
    assert r.status_code == 201, r.text
    cid = r.json()["conversation_id"]
    assert r.json()["messages"][-1]["text"] == QUESTION
    r = await client.post(f"/api/conversations/{cid}/messages", headers=H, json={"text": answer})
    assert r.status_code == 200, r.text
    return cid, r.json()


async def test_yes_after_clarification_routes_to_the_leader(client, indexed, rec, monkeypatch):  # noqa: ANN001, F811
    """Covers: RTE-18, RTE-20"""
    claims, care, sales = indexed["claims"]["agent_id"], indexed["care"]["agent_id"], indexed["sales"]["agent_id"]
    await _desk(care)
    monkeypatch.setattr(catalog, "stage_a", two_rounds(
        [{"agent_id": claims, "score": 0.815}, {"agent_id": care, "score": 0.719}, {"agent_id": sales, "score": 0.60}],
        [{"agent_id": claims, "score": 0.796}, {"agent_id": care, "score": 0.68}, {"agent_id": sales, "score": 0.56}]))
    rec.realtime.append("I can check that for you, I just need to confirm a couple of details first.")
    cid, body = await _ask_then_answer(client, rec, "Yes.")
    assert body["agent"]["id"] == claims  # not the default agent
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        call = await s.get(Call, conv.current_call_id)
    last = conv.routing[-1]
    assert last["method"] == "clarified" and last["decided_by"] == "leader" and last["agent_id"] == claims
    assert call.meta["handoff"] == {"reason": "Routed by the front desk", "summary": f"{ASK} / Yes.", "routed": True}
    system, *history = rec.requests[-1]
    assert f"What the caller has told us so far: {ASK} / Yes." in system["content"]
    assert "Never ask the caller to repeat their request." in system["content"]
    said = [(m["role"], m.get("content")) for m in history if m["role"] in ("user", "assistant")]
    assert ("user", ASK) in said and ("assistant", QUESTION) in said and said[-1] == ("user", "Yes.")  # the whole request


async def test_no_after_clarification_routes_to_the_default(client, indexed, rec, monkeypatch):  # noqa: ANN001, F811
    """Covers: RTE-19"""
    claims, care, sales = indexed["claims"]["agent_id"], indexed["care"]["agent_id"], indexed["sales"]["agent_id"]
    await _desk(care)
    ranked = [{"agent_id": claims, "score": 0.79}, {"agent_id": care, "score": 0.72}, {"agent_id": sales, "score": 0.6}]
    monkeypatch.setattr(catalog, "stage_a", two_rounds(ranked, ranked))
    _, body = await _ask_then_answer(client, rec, "No, something else.")
    assert body["agent"]["id"] == care
    # a different leader after the question is not confirmed either
    rec2 = await supervisor.route("northgate-health", "member", "billing", channel="text", clarifications_used=1,
                                  prior_leader=sales, answer="Yes")
    assert rec2["method"] == "default" and rec2["agent_id"] == care
    assert supervisor.is_negative("Neither of those") and supervisor.is_negative("no") and not supervisor.is_negative("Yes.")


def test_handoff_block_is_the_spec_block():
    """Covers: XFR-09"""
    block = prompt_mod.handoff_block({"reason": "Caller wants dental cover details", "summary": "Asked about dental add-on."})
    assert block.startswith("# How this caller reached you\nThey were passed to you because: Caller wants dental cover details")
    assert "What the caller has told us so far: Asked about dental add-on." in block
    assert "Never ask the caller to repeat their request." in block
    assert "Once they are verified, go straight back to their request. Do not ask how you can help." in block
    assert prompt_mod.handoff_block(None) == "" and prompt_mod.handoff_block({}) == ""
    assert "(none)" in prompt_mod.handoff_block({"reason": "", "summary": "", "routed": True})


async def test_direct_call_has_the_after_verification_rule(client, seeded):  # noqa: ANN001
    """Covers: XFR-09"""
    from voiceai.runtime.session import AgentSession

    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})
    assert r.status_code == 200, r.text
    session = await AgentSession.open(r.json()["call_id"], "northgate-health")
    text = session.prompt()
    assert "How this caller reached you" not in text
    assert "After verification, carry on with what the caller already asked for." in text
