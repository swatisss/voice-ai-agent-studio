"""CP-0046: the fixes from the pre-demo QA (grounded amounts, third parties, hand-offs, plain speech, front-desk questions, defaults).

Typed conversations on the fake LLM; no network.

Covers: QA-01, QA-02, QA-03, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-12, QA-14
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from tests.conftest import script
from tests.test_agent_transfer import Script
from tests.test_capability_catalog import run_index_jobs
from tests.test_front_desk_safety import _open, _desk, prefer
from tests.test_runtime import _say, _start
from voiceai.db import sessionmaker
from voiceai.learning import scoring
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent, Conversation
from voiceai.routing import catalog, decision, front_desk, supervisor
from voiceai.runtime import escalation, speech
from voiceai.runtime.session import AgentSession
from voiceai.runtime.tools import BUILTIN_SCHEMAS
from voiceai.schemas import THIRD_PARTY_RULE, EvaluationConfig, Policy

PROMPT = (Path(__file__).resolve().parents[3] / "specs" / "prompts" / "agent-system-prompt.md").read_text(encoding="utf-8")
H = {"X-Tenant-Id": "northgate-health"}


def ev(seq: int, kind: str, text: str | None = None, **data) -> CallEvent:  # noqa: ANN003
    return CallEvent(seq=seq, kind=kind, text=text, data=data)


def test_prompt_carries_the_qa_rules():
    """Covers: QA-01, QA-03"""
    assert "never from a knowledge article" in PROMPT and "(excess, premium, limits, dates, claims, authorisations)" in PROMPT
    assert "never escalate because of it: the system hands the call over after three failed attempts" in PROMPT
    assert "never say a format such as YYYY-MM-DD aloud" in PROMPT


def test_stated_amounts_need_a_source():
    """Covers: QA-02"""
    invented = [ev(1, "user", "What's my excess?"), ev(2, "assistant", "Your excess is £250 per policy year.")]
    v = scoring.amounts_verdict(invented)
    assert v["verdict"] == "fail" and "250" in v["reason"] and v["evidence"]["seqs"] == [2]
    looked_up = [ev(1, "user", "What's my excess?"), ev(2, "tool_result", None, name="get_policy_details", result={"cover": {"excess": 100}}),
                 ev(3, "assistant", "Your excess is £100 per policy year.")]
    assert scoring.amounts_verdict(looked_up)["verdict"] == "pass"
    assert scoring.amounts_verdict([ev(1, "assistant", "Hello", greeting=True), ev(2, "assistant", "Anything else?")])["verdict"] == "n/a"
    assert scoring.amounts_verdict([ev(1, "tool_result", None, result={"amount": 1250.5}), ev(2, "assistant", "That is $1,250.50 in total.")])["verdict"] == "pass"
    assert "knowledge.amounts_supported" in {c.key for c in scoring.CODE_CHECKS}


async def test_third_party_rule_is_a_default(client, seeded):  # noqa: ANN001
    """Covers: QA-04"""
    assert THIRD_PARTY_RULE in Policy().never
    for key in ("care", "sales", "claims"):
        agent = (await client.get(f"/api/agents/{seeded[key]['agent_id']}", headers=H)).json()
        assert THIRD_PARTY_RULE in agent["draft_config"]["policy"]["never"], key


async def test_acknowledgement_comes_before_the_handoff_line(client, seeded, fake_llm):  # noqa: ANN001
    """Covers: QA-05"""
    esc = ("escalate_to_human", {"reason_category": "knowledge_gap", "reason_detail": "newborn", "acknowledgement": "Congratulations on the baby!"})
    fake_llm(script(FakeReply(tool_calls=[esc])))
    out = await _say(client, await _start(client, seeded), "I had a baby last week, how do I add her?")
    assert out["reply"].startswith("Congratulations on the baby! I'm connecting you with a colleague")
    plain = ("escalate_to_human", {"reason_category": "caller_requested", "reason_detail": "wants a person"})
    fake_llm(script(FakeReply(tool_calls=[plain])))
    out2 = await _say(client, await _start(client, seeded), "A person please")
    assert out2["reply"].startswith("I'm connecting you with a colleague")


def test_escalation_categories_are_explained():
    """Covers: QA-06"""
    tool = next(t["function"] for t in BUILTIN_SCHEMAS if t["function"]["name"] == "escalate_to_human")
    for word in ("caller_requested only if the caller asked for a person", "knowledge_gap", "capability_gap", "policy_required", "frustration"):
        assert word in tool["description"]
    assert tool["parameters"]["properties"]["acknowledgement"]["maxLength"] == 140
    assert "caller_requested only when the caller asked for a person" in PROMPT


async def test_voice_replies_have_no_markdown(client, seeded, fake_llm):  # noqa: ANN001
    """Covers: QA-07"""
    assert speech.plain("**Gold** plan, see [the guide](https://x.test/g) and `code`\n- one\n1. two") == "Gold plan, see the guide and code\none\ntwo"
    text = "**Gold** plan, (format: YYYY-MM-DD)"
    for channel, expected in (("voice", "Gold plan, (format: YYYY-MM-DD)"), ("simulation", text)):
        fake_llm(script(FakeReply(text=text)))
        async with sessionmaker()() as s:
            call = Call(tenant_id="northgate-health", agent_id=seeded["care"]["agent_id"], agent_version_id=seeded["care"]["version_id"],
                        channel=channel, is_eval=channel == "simulation")
            s.add(call)
            await s.commit()
        session = await AgentSession.open(call.id, "northgate-health")
        spoken = "".join([c async for c in session.respond("Which plan?")])
        assert spoken.strip() == expected, channel
        async with sessionmaker()() as s:
            stored = (await s.scalars(select(CallEvent.text).where(CallEvent.call_id == call.id, CallEvent.kind == "assistant"))).all()
        assert stored[-1] == expected, channel


async def test_a_bare_yes_asks_what_the_caller_needs(client, seeded, fake_llm, monkeypatch):  # noqa: ANN001
    """Covers: QA-08"""
    fake_llm(Script())
    await run_index_jobs()
    care = seeded["care"]["agent_id"]
    monkeypatch.setattr(catalog, "stage_a", prefer(care, seeded["claims"]["agent_id"], seeded["sales"]["agent_id"]))
    await _desk(max_clarifications=1)
    out = await _open(client, "Yes")
    assert out["agent"] is None and out["messages"][-1]["text"] == "What can I help you with?"
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, out["conversation_id"])
    assert conv.clarifications == 0 and conv.routing[-1]["method"] == "clarify" and conv.routing[-1]["bare"] is True
    r = await client.post(f"/api/conversations/{out['conversation_id']}/messages", headers=H, json={"text": "I want to check on my claim"})
    assert r.status_code == 200 and r.json()["agent"]["id"] == care  # the clarification is still unused, the real request routes


async def test_clarifying_question_needs_two_real_candidates(client, seeded, fake_llm, monkeypatch):  # noqa: ANN001
    """Covers: QA-09"""
    fake_llm(Script())
    await run_index_jobs()
    care, claims, sales = seeded["care"]["agent_id"], seeded["claims"]["agent_id"], seeded["sales"]["agent_id"]

    def ranked(*scores):  # noqa: ANN002, ANN202
        async def fake(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
            return [{"agent_id": a, "score": sc} for a, sc in zip((care, claims, sales), scores, strict=False)]
        return fake

    monkeypatch.setattr(catalog, "stage_a", ranked(0.55, 0.20, 0.10))
    one = await supervisor.route("northgate-health", "member", "something about cover", channel="text")
    assert one["method"] == "embedding" and one["agent_id"] == care and one["clarification"] is None
    monkeypatch.setattr(catalog, "stage_a", ranked(0.55, 0.50, 0.10))
    two = await supervisor.route("northgate-health", "member", "something about cover", channel="text")
    assert two["method"] == "clarify" and two["clarification"]


async def test_out_of_scope_gets_one_line_and_no_agent(client, seeded, fake_llm, monkeypatch):  # noqa: ANN001
    """Covers: QA-10"""
    fake_llm(Script())
    await run_index_jobs()
    care, claims = seeded["care"]["agent_id"], seeded["claims"]["agent_id"]

    async def weak(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
        return [{"agent_id": care, "score": 0.18}, {"agent_id": claims, "score": 0.12}]

    monkeypatch.setattr(catalog, "stage_a", weak)
    out = await _open(client, "What's the weather in Leeds?")
    assert out["agent"] is None and out["messages"][-1]["text"].startswith("I can help with health insurance questions")
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, out["conversation_id"])
    assert conv.routing[-1]["method"] == "out_of_scope" and conv.clarifications == 0 and conv.status == "active"
    await _desk(out_of_scope_line="That is outside what I can do. Is it about your health policy?")
    out2 = await _open(client, "Can I apply for a job?")
    assert out2["messages"][-1]["text"] == "That is outside what I can do. Is it about your health policy?"


def test_decision_budgets_and_latency_default(monkeypatch):
    """Covers: QA-11, QA-12"""
    from voiceai.config import get_settings

    assert decision.TIMEOUT_DEFAULT_MS == {"voice": 1500, "text": 2500}
    monkeypatch.setenv("DECISION_MODEL_TIMEOUT_VOICE_MS", "700")
    get_settings.cache_clear()
    assert decision.timeout_ms("voice") == 700
    get_settings.cache_clear()
    assert EvaluationConfig().latency_p95_ms == 4000 and EvaluationConfig(latency_p95_ms=2000).latency_p95_ms == 2000


def test_emergency_numbers_are_not_packet_entities():
    """Covers: QA-14"""
    kept = escalation.clean_entities({"member_ref": "NGH-410237", "Emergency number": "999", "Samaritans number": "116 123", "claim_id": "CL-70231",
                                      "phone": "999"})
    assert kept == {"member_ref": "NGH-410237", "claim_id": "CL-70231"}
