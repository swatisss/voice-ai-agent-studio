"""English and Hindi with switching mid-call: the setting, the publish rule, the prompt, turn language, tool arguments,
knowledge queries, the Hindi safety screen, realtime transcription, scenario language and the new-agent default.

Covers: LANG-01, LANG-02, LANG-03, LANG-04, LANG-05, LANG-06, LANG-07, LANG-08, LANG-09, LANG-10, LANG-11
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from tests.conftest import script
from voiceai import jobs, prompts
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply
from voiceai.learning.evaluate import LANGUAGE_LINES
from voiceai.models import AgentVersion, CallEvent, Escalation
from voiceai.runtime import escalation, language
from voiceai.seed.catalog import SANDBOX_TENANT

H = {"X-Tenant-Id": "northgate-health"}
SANDBOX = {"X-Tenant-Id": SANDBOX_TENANT}
CHEST_PAIN_HI = "मुझे सीने में दर्द हो रहा है"


async def _draft(client, agent_id: str) -> dict[str, Any]:  # noqa: ANN001
    return (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]


async def _bilingual(client, seeded) -> str:  # noqa: ANN001
    """The seeded member-services agent made bilingual on the realtime pipeline and published."""
    agent_id = seeded["care"]["agent_id"]
    cfg = await _draft(client, agent_id)
    cfg["languages"] = ["en", "hi"]
    cfg["voice"]["pipeline"] = "realtime"
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})).status_code == 200
    r = await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={})
    assert r.status_code == 200, r.text
    return agent_id


async def _call(client, agent_id: str) -> str:  # noqa: ANN001
    r = await client.post("/api/calls", headers=H, json={"agent_id": agent_id, "channel": "text"})
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


async def _say(client, call_id: str, text: str) -> dict[str, Any]:  # noqa: ANN001
    r = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


async def _events(call_id: str) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())


async def test_languages_setting_is_validated_and_versioned(client, seeded):
    """Covers: LANG-01"""
    agent_id = seeded["claims"]["agent_id"]
    cfg = await _draft(client, agent_id)
    cfg["voice"]["pipeline"] = "realtime"  # Hindi needs the realtime pipeline to publish (LANG-02)
    assert cfg.get("languages", ["en"]) == ["en"]  # absent in the seeded draft means English only
    for bad in (["hi"], ["en", "fr"], []):
        r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**cfg, "languages": bad}})
        assert r.status_code == 422, bad
    cfg.pop("languages", None)
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})).json()["draft_config"]["languages"] == ["en"]
    r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**cfg, "languages": ["hi", "en"]}})
    assert r.status_code == 200 and r.json()["draft_config"]["languages"] == ["en", "hi"]
    v = (await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={})).json()
    async with sessionmaker()() as s:
        assert (await s.get(AgentVersion, v["id"])).config["languages"] == ["en", "hi"]


async def test_hindi_needs_the_realtime_pipeline_to_publish(client, seeded):
    """Covers: LANG-02"""
    agent_id = seeded["care"]["agent_id"]  # a cascade agent
    cfg = await _draft(client, agent_id)
    assert cfg["voice"]["pipeline"] == "cascade"
    r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**cfg, "languages": ["en", "hi"]}})
    assert r.status_code == 200  # the builder may be mid-edit
    before = len((await client.get(f"/api/agents/{agent_id}/versions", headers=H)).json()["items"])
    r = await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={})
    assert r.status_code == 422 and r.json()["error"] == "language_needs_realtime"
    assert len((await client.get(f"/api/agents/{agent_id}/versions", headers=H)).json()["items"]) == before
    cfg = await _draft(client, agent_id)
    cfg["voice"]["pipeline"] = "realtime"
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})).status_code == 200
    assert (await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={})).status_code == 200


async def test_language_block_only_for_bilingual_agents(client, seeded, fake_llm):
    """Covers: LANG-03, LANG-04"""
    from voiceai.runtime.prompt import system_prompt

    block = prompts.fragment("agent-system-prompt", "Language block (bilingual agents):")
    assert block.startswith("# Language") and "search_knowledge queries in English" in block
    english = {"persona": {"name": "Olivia", "style": "Warm."}, "policy": {}, "skills": []}
    from datetime import datetime

    now = datetime(2026, 11, 12)
    plain = system_prompt(english, "Northgate Health", None, now)
    assert "# Language" not in plain and "{{" not in plain
    bilingual = system_prompt({**english, "languages": ["en", "hi"]}, "Northgate Health", None, now)
    assert block in bilingual
    assert " ".join(bilingual.replace(block, "").split()) == " ".join(plain.split())  # otherwise the same (blank lines aside)

    seen: list[str] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        seen.append(messages[0]["content"])
        return FakeReply(text="Okay.")

    fake_llm(responder)
    await _say(client, await _call(client, await _bilingual(client, seeded)), "Hello")
    assert block in seen[-1]  # the text channel of a bilingual (realtime) agent carries the block


def test_turn_language():
    """Covers: LANG-05"""
    assert language.turn_language("मेरा claim status बताइए") == "hi"
    assert language.turn_language("mera claim status batao") == "en"
    assert language.turn_language("What is my excess?") == "en"


async def test_user_events_carry_the_language_on_bilingual_calls(client, seeded, fake_llm):
    """Covers: LANG-05"""
    fake_llm(script(FakeReply(text="ज़रूर।"), FakeReply(text="Sure.")))
    call_id = await _call(client, await _bilingual(client, seeded))
    await _say(client, call_id, "मेरा claim status बताइए")
    await _say(client, call_id, "Actually, in English please")
    users = [e for e in await _events(call_id) if e.kind == "user"]
    assert [e.data.get("language") for e in users] == ["hi", "en"]


async def test_identifiers_in_devanagari_are_normalised_before_tools(client, seeded, fake_llm):
    """Covers: LANG-06"""
    assert language.normalise_text("१४ मार्च १९८४") == "14 March 1984"
    assert language.normalise_text("१ फ़रवरी") == "1 February" and language.normalise_text("३ सितम्बर") == "3 September"
    args = {"member_id": "NGH-४१०२३७", "date_of_birth": "१९८४-०३-१४"}  # the seeded member NGH-410237, 1984-03-14
    fake_llm(script(FakeReply(tool_calls=[("verify_member", args)]), FakeReply(text="धन्यवाद, आप verified हैं।")))
    call_id = await _call(client, await _bilingual(client, seeded))
    await _say(client, call_id, "मेरा membership number NGH-४१०२३७ है")
    result = next(e for e in await _events(call_id) if e.kind == "tool_result" and e.data["name"] == "verify_member")
    assert result.data["result"].get("verified") is True


async def test_hindi_knowledge_query_is_bounced(client, seeded, fake_llm):
    """Covers: LANG-07"""
    fake_llm(script(
        FakeReply(tool_calls=[("search_knowledge", {"query": "नवजात को प्लान में कैसे जोड़ें"})]),
        FakeReply(tool_calls=[("search_knowledge", {"query": "नवजात को प्लान में कैसे जोड़ें"})]),
        FakeReply(text="एक पल।"),
    ))
    call_id = await _call(client, await _bilingual(client, seeded))
    out = await _say(client, call_id, "नवजात को प्लान में कैसे जोड़ें?")
    assert not out["escalated"]  # two bounced queries are not a no-answer streak (ES-02 would escalate)
    results = [e for e in await _events(call_id) if e.kind == "tool_result" and e.data["name"] == "search_knowledge"]
    assert len(results) == 2 and all(r.data["result"]["error"] == "query_not_english" for r in results)


async def test_hindi_safety_phrases_on_every_agent(client, seeded, fake_llm):
    """Covers: LANG-08"""
    fake_llm(lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    english_agent = seeded["care"]["agent_id"]
    hi = await _say(client, cid := await _call(client, english_agent), CHEST_PAIN_HI)
    assert hi["escalated"] and hi["reply"].startswith(escalation.SAFETY_MESSAGE_HI[:20])
    latin = await _say(client, cid2 := await _call(client, english_agent), "mujhe seene mein dard hai")
    assert latin["escalated"] and "call 999" in latin["reply"]
    async with sessionmaker()() as s:
        for c in (cid, cid2):
            assert (await s.scalar(select(Escalation).where(Escalation.call_id == c))).reason_category == "safety"
    assert escalation.safety_match("आत्महत्या") and escalation.safety_match("Khud Ko Maar")
    assert not escalation.safety_match("मेरा claim status बताइए")


async def test_hindi_safety_on_the_realtime_turn_policy(client, seeded):
    """Covers: LANG-08 (the realtime bridge's turn decision, RV-08)"""
    from voiceai.runtime.session import AgentSession

    agent_id = await _bilingual(client, seeded)
    session = await AgentSession.open(await _call(client, agent_id), "northgate-health")
    decision = await session.caller_turn(CHEST_PAIN_HI)
    assert decision.say == escalation.SAFETY_MESSAGE_HI and not decision.model_turn
    await session.commit(decision)
    assert session.state.escalated


async def test_realtime_transcription_has_no_language(client, seeded):
    """Covers: LANG-09"""
    try:
        from voiceai.voice.realtime import session_update
    except ImportError as exc:  # the voice stack's native libraries are blocked on some locked-down Windows machines
        pytest.skip(f"voice stack unavailable: {exc}")
    from voiceai.runtime.session import AgentSession
    from voiceai.voice.turn_detection import TurnSettings

    session = await AgentSession.open(await _call(client, await _bilingual(client, seeded)), "northgate-health")
    update = session_update(session, TurnSettings())
    assert "language" not in (update["session"]["audio"]["input"].get("transcription") or {})
    assert "# Language" in update["session"]["instructions"]


async def test_scenario_language_reaches_the_simulator(client, seeded, fake_llm):
    """Covers: LANG-10"""
    seen: list[str] = []
    script_lines = ["नमस्ते, मुझे claim के बारे में पूछना है।", "Okay, and what about my excess?", "धन्यवाद।"]
    lines = iter(script_lines)

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        prompt = messages[-1]["content"] if messages else ""
        if role == "simulator":
            seen.append(prompt)
            return next(lines, "[HANGUP]")  # noqa: B023 (reset after the publish's own run)
        if role == "realtime":
            return FakeReply(text="ज़रूर।")
        if role == "judge":
            keys = [ln.split(":", 1)[0] for ln in prompt.split("Checks:\n", 1)[1].split("\n\nReturn JSON", 1)[0].splitlines()]
            return {"outcome": "resolved", "goal_met": True, "grounded": True, "policy_violations": [], "notes": "",
                    "checks": {k: {"verdict": "pass", "reason": "ok"} for k in keys}}
        if role == "analysis":
            return {"outcome": "resolved", "intent": "x", "root_cause": "none", "gap_summary": "", "caller_goal": "x",
                    "resolution_summary": "", "sentiment_start": "neutral", "sentiment_end": "neutral"}
        raise AssertionError(role)

    fake_llm(responder)
    agent_id = await _bilingual(client, seeded)
    await jobs.drain()  # the test run started by the publish (TEST-08)
    seen.clear()
    lines = iter(script_lines)
    r = await client.post(f"/api/agents/{agent_id}/scenarios", headers=H,
                          json={"name": "Switches", "caller_goal": "You want to ask about your claim.", "language": "mixed"})
    assert r.status_code == 200 and r.json()["language"] == "mixed"
    r = await client.post(f"/api/agents/{agent_id}/test-runs", headers=H, json={"scenario_ids": [r.json()["id"]], "repeats": 1})
    assert r.status_code == 200, r.text
    await jobs.drain()
    run = (await client.get(f"/api/test-runs/{r.json()['eval_run_id']}", headers=H)).json()
    assert run["status"] == "done", run
    assert seen and all(LANGUAGE_LINES["mixed"] in p for p in seen)
    call_id = run["results"][0]["call_id"]
    langs = {e.data.get("language") for e in await _events(call_id) if e.kind == "user"}
    assert langs == {"en", "hi"}


async def test_new_agents_default_to_bilingual_realtime_where_allowed(client, seeded):
    """Covers: LANG-11"""
    others = {a["id"]: a["draft_config"] for a in (await client.get("/api/agents", headers=H)).json()["items"]}
    r = await client.post("/api/agents", headers=H, json={"name": "Travel desk", "description": "Travel questions."})
    assert r.status_code == 200, r.text
    cfg = r.json()["draft_config"]
    assert cfg["voice"]["pipeline"] == "realtime" and cfg["languages"] == ["en", "hi"]
    assert (await client.post(f"/api/agents/{r.json()['id']}/publish", headers=H, json={})).status_code == 200

    r = await client.post("/api/agents", headers=SANDBOX, json={"name": "Sandbox desk", "description": "Questions."})
    assert r.status_code == 200, r.text
    assert r.json()["draft_config"]["voice"]["pipeline"] == "cascade" and r.json()["draft_config"]["languages"] == ["en"]

    r = await client.post("/api/agents", headers=H, json={"name": "English desk", "description": "Questions.",
                                                          "draft_config": {"voice": {"pipeline": "cascade"}, "languages": ["en"]}})
    assert r.json()["draft_config"]["voice"]["pipeline"] == "cascade" and r.json()["draft_config"]["languages"] == ["en"]

    after = {a["id"]: a["draft_config"] for a in (await client.get("/api/agents", headers=H)).json()["items"]}
    assert all(after[k] == v for k, v in others.items())  # existing agents unchanged
