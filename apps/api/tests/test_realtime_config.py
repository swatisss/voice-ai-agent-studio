"""Pipeline and telephony settings, the speech role, runtime methods for externally driven turns and realtime evaluation.

Covers: RV-01, RV-14, RV-15, DM-06, LG-12, LG-13, RT-10, DEP-04
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import script
from voiceai import jobs
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply, Gateway, Usage, reset_gateway
from voiceai.models import Agent, AgentVersion, Call, CallEvent
from voiceai.runtime.session import AgentSession, create_call

H = {"X-Tenant-Id": "evergreen-care"}


async def _draft(client, agent_id: str) -> dict:  # noqa: ANN001
    return (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]


async def _save(client, agent_id: str, cfg: dict):  # noqa: ANN001, ANN202
    return await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})


async def test_pipeline_value_defaults_and_is_versioned(client, seeded):
    """Covers: RV-01"""
    care, claims = seeded["care"]["agent_id"], seeded["claims"]["agent_id"]
    cfg = await _draft(client, care)
    cfg["voice"].pop("pipeline", None)
    assert (await _save(client, care, cfg)).status_code == 200
    assert (await _draft(client, care))["voice"]["pipeline"] == "cascade"  # absent means cascade
    cfg["voice"]["pipeline"] = "telegram"
    assert (await _save(client, care, cfg)).status_code == 422
    cfg["voice"]["pipeline"] = "realtime"
    assert (await _save(client, care, cfg)).status_code == 200
    assert (await client.post(f"/api/agents/{care}/publish", headers=H, json={"change_note": "realtime"})).status_code == 200
    async with sessionmaker()() as s:
        agent = await s.get(Agent, care)
        assert (await s.get(AgentVersion, agent.published_version_id)).config["voice"]["pipeline"] == "realtime"
        claims_agent = await s.get(Agent, claims)
        assert (await s.get(AgentVersion, claims_agent.published_version_id)).config["voice"]["pipeline"] == "realtime"


async def test_transfer_voice_and_speech_model_validation(client, seeded):
    """Covers: DM-06"""
    agent = seeded["claims"]["agent_id"]
    cfg = await _draft(client, agent)
    for bad in ({"telephony": {"transfer_to": "0123"}}, {"voice": {**cfg["voice"], "realtime": {"voice": "not-a-voice"}}},
                {"models": {**cfg["models"], "speech": "groq:openai/gpt-oss-120b"}}):
        assert (await _save(client, agent, {**cfg, **bad})).status_code == 422, bad
    for good in ("+15557654321", "sip:claims@example.com"):
        assert (await _save(client, agent, {**cfg, "telephony": {"transfer_to": good}})).status_code == 200
    ok = {**cfg, "voice": {**cfg["voice"], "realtime": {"voice": "marin"}}, "models": {**cfg["models"], "speech": "openai:gpt-realtime-2.1"}}
    assert (await _save(client, agent, ok)).status_code == 200


def test_speech_role_and_model_split(monkeypatch):
    """Covers: LG-12"""
    g = Gateway()
    ref = g.speech_ref()
    price = g.models[ref]
    assert ref.startswith("openai:") and price["kind"] == "speech" and price["audio_input"] and price["audio_output"] and price["input"] and price["output"]
    assert g.speech_voices() and ref not in g.selectable()
    monkeypatch.setenv("LLM_ROLE_SPEECH", "openai:gpt-4.1-mini")
    with pytest.raises(ValueError):
        Gateway()  # a chat model in the speech role
    monkeypatch.delenv("LLM_ROLE_SPEECH")
    monkeypatch.setenv("LLM_ROLE_REALTIME", ref)
    with pytest.raises(ValueError):
        Gateway()  # a speech model in a chat role
    monkeypatch.delenv("LLM_ROLE_REALTIME")
    monkeypatch.setenv("LLM_ROLE_SPEECH", ref)
    assert Gateway().speech_ref() == ref
    reset_gateway()


async def test_speech_cost_and_models_endpoint(client):
    """Covers: LG-13"""
    g = Gateway()
    ref = g.speech_ref()
    p = g.models[ref]
    usage = Usage(input_tokens=2_000_000, output_tokens=2_000_000, audio_input_tokens=1_000_000, audio_output_tokens=1_000_000)
    assert g.usage_cost(ref, usage) == pytest.approx(p["input"] + p["output"] + p["audio_input"] + p["audio_output"])
    body = (await client.get("/api/models")).json()
    assert ref not in body["selectable"] and body["speech"]["models"] == [ref] and body["speech"]["voices"]


async def test_healthz_reports_twilio_from_dotenv_settings(client, monkeypatch):
    """Covers: DEP-04"""
    from voiceai.config import get_settings

    assert (await client.get("/healthz")).json()["providers"]["twilio"] is False
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    get_settings.cache_clear()
    try:
        assert (await client.get("/healthz")).json()["providers"]["twilio"] is True
    finally:
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
        get_settings.cache_clear()


async def _session(seeded, agent_key: str = "care") -> AgentSession:
    async with sessionmaker()() as s:
        call = await create_call(s, "evergreen-care", seeded[agent_key]["agent_id"], "voice")
        await s.commit()
    return await AgentSession.open(call.id, "evergreen-care")


async def test_run_tool_matches_the_turn_loop(client, seeded, fake_llm):
    """Covers: RT-10"""
    verify = ("verify_member", {"member_id": "482913", "date_of_birth": "1986-04-12"})
    claim = ("get_claim_status", {"claim_id": "C-20931"})
    fake_llm(script(FakeReply(tool_calls=[claim]), FakeReply(tool_calls=[verify]), FakeReply(tool_calls=[claim]), FakeReply(text="Paid.")))
    text_call = await _session(seeded)
    await text_call.start()
    await text_call.reply("What about claim C-20931?")
    async with sessionmaker()() as s:
        loop_events = [(e.kind, (e.data or {}).get("name"), (e.data or {}).get("ok")) for e in
                       (await s.scalars(select(CallEvent).where(CallEvent.call_id == text_call.call_id, CallEvent.kind.in_(("tool_call", "tool_result"))).order_by(CallEvent.seq))).all()]
    driven = await _session(seeded)
    await driven.start()
    blocked = await driven.run_tool("get_claim_status", {"claim_id": "C-20931"})
    assert "identity_not_verified" in blocked
    await driven.run_tool("verify_member", {"member_id": "482913", "date_of_birth": "1986-04-12"})
    assert driven.state.verified_member_ref == "EVG-482913"
    assert "paid" in (await driven.run_tool("get_claim_status", '{"claim_id": "C-20931"}')).lower()
    async with sessionmaker()() as s:
        driven_events = [(e.kind, (e.data or {}).get("name"), (e.data or {}).get("ok")) for e in
                         (await s.scalars(select(CallEvent).where(CallEvent.call_id == driven.call_id, CallEvent.kind.in_(("tool_call", "tool_result"))).order_by(CallEvent.seq))).all()]
    assert loop_events[:2] == driven_events[:2] and loop_events[0] == ("tool_call", "get_claim_status", None)
    assert driven_events[1][2] is False  # the gate blocked it in both channels

    await driven.record_turn("thanks", "You're welcome.", latency_ms=420, usage=Usage(input_tokens=100, output_tokens=20, cost_usd=0.01))
    assert driven.state.turns == 1 and driven.state.tokens_in == 100 and driven.state.latencies_ms == [420]
    async with sessionmaker()() as s:
        kinds = [e.kind for e in (await s.scalars(select(CallEvent).where(CallEvent.call_id == driven.call_id).order_by(CallEvent.seq))).all()]
    assert kinds[-2:] == ["user", "assistant"]


async def test_realtime_agent_is_evaluated_on_the_text_brain(client, seeded, fake_llm):
    """Covers: RV-14"""
    from tests.test_learning import _cluster, responder

    roles: list[str] = []
    inner = responder()

    def spy(role, messages, tools):  # noqa: ANN001, ANN202
        roles.append(role)
        return inner(role, messages, tools)

    fake_llm(spy)
    agent = seeded["care"]["agent_id"]
    cfg = await _draft(client, agent)
    cfg["voice"]["pipeline"] = "realtime"
    assert (await _save(client, agent, cfg)).status_code == 200
    assert (await client.post(f"/api/agents/{agent}/publish", headers=H, json={"change_note": "realtime"})).status_code == 200
    newborn = await _cluster(client, "Adding a newborn to coverage")
    await client.post(f"/api/insights/clusters/{newborn['id']}/draft-fix", headers=H)
    await jobs.drain()
    pid = (await client.get(f"/api/insights/clusters/{newborn['id']}", headers=H)).json()["proposals"][0]["id"]
    await client.post(f"/api/proposals/{pid}/evaluate", headers=H)
    await jobs.drain()
    summary = (await client.get(f"/api/proposals/{pid}", headers=H)).json()["eval_run"]["summary"]
    assert summary["pipeline"] == "realtime" and summary["fidelity"] == "text_approximation"
    assert "speech" not in roles and "realtime" in roles


async def test_live_changes_are_refused_on_realtime_calls(client, seeded, monkeypatch):
    """Covers: RV-15"""
    from voiceai.config import get_settings
    from voiceai.llm.gateway import reset_gateway

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # both voice calls must be admitted (ADM-02)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    get_settings.cache_clear()
    reset_gateway()
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["claims"]["agent_id"], "channel": "voice"})
    call_id = r.json()["call_id"]
    patch = await client.patch(f"/api/calls/{call_id}/live", headers=H, json={"turn_detection": {"mode": "vad"}})
    assert patch.status_code == 409 and patch.json()["error"] == "realtime_pipeline"
    cascade = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "voice"})
    ok = await client.patch(f"/api/calls/{cascade.json()['call_id']}/live", headers=H, json={"turn_detection": {"mode": "vad"}})
    assert ok.status_code == 200
