"""Call scoring: scorecards, checks from the version config, sampling, reviews, calibration, rollups and drift.

Covers: SC-01, SC-02, SC-03, SC-04, SC-05, SC-06, SC-07, SC-08, SC-09, SC-10, SC-11, SC-12, KN-07, DM-08, API-08, API-09
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from voiceai import jobs
from voiceai.db import new_id, sessionmaker, utcnow
from voiceai.learning import score_report, scoring
from voiceai.llm.gateway import FakeReply
from voiceai.models import Agent, AgentVersion, Call, CallEvent, CallFeedback, CallScorecard, CheckReview, Escalation, Job

H = {"X-Tenant-Id": "evergreen-care"}
ANALYSIS = {"outcome": "resolved", "intent": "claim_status", "root_cause": "none", "gap_summary": "", "caller_goal": "Check a claim.",
            "resolution_summary": "Explained claim.", "sentiment_start": "neutral", "sentiment_end": "positive"}


def responder(verdicts: dict[str, Any] | None = None, realtime: list[FakeReply] | None = None, judge_calls: list[str] | None = None):  # noqa: ANN201
    """Fake LLM: realtime replies in order, a fixed analysis, and a judge that answers `verdicts` (default: every check passes)."""
    queue = list(realtime or [])

    def r(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:  # noqa: ANN401
        prompt = messages[-1]["content"] if messages else ""
        if role == "realtime":
            return queue.pop(0) if queue else FakeReply(text="Okay, I can help with that.")
        if role == "analysis":
            return ANALYSIS
        if role == "judge":
            if judge_calls is not None:
                judge_calls.append(prompt)
            keys = [line.split(":", 1)[0] for line in prompt.split("Checks:\n", 1)[1].split("\n\nReturn JSON", 1)[0].splitlines()]
            checks = verdicts if verdicts is not None else {k: {"verdict": "pass", "reason": "ok", "seqs": [2]} for k in keys}
            return {"outcome": "resolved", "goal_met": True, "grounded": True, "policy_violations": [], "notes": "", "checks": checks}
        if role == "drafting":
            return {"name": "x", "description": "y"}
        raise AssertionError(role)

    return r


async def _text_call(client, agent_id: str, *lines: str) -> str:  # noqa: ANN001
    call_id = (await client.post("/api/calls", headers=H, json={"agent_id": agent_id, "channel": "text"})).json()["call_id"]
    for line in lines:
        await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": line})
    await client.post(f"/api/calls/{call_id}/end", headers=H)
    return call_id


async def _card(call_id: str) -> CallScorecard | None:
    async with sessionmaker()() as s:
        return await s.scalar(select(CallScorecard).where(CallScorecard.call_id == call_id))


def _verdicts(card: CallScorecard) -> dict[str, str]:
    return {c["key"]: c["verdict"] for c in card.checks}


async def _config(seeded) -> dict[str, Any]:  # noqa: ANN001
    async with sessionmaker()() as s:
        return (await s.get(AgentVersion, seeded["care"]["version_id"])).config


async def _manual_call(seeded, events: list[tuple[str, str | None, dict]], *, outcome: str = "resolved", meta: dict | None = None,  # noqa: ANN001
                       channel: str = "text", is_eval: bool = False, started=None, call_id: str | None = None) -> str:  # noqa: ANN001
    async with sessionmaker()() as s:
        start = started or utcnow() - timedelta(minutes=5)
        call = Call(id=call_id or new_id(), tenant_id="evergreen-care", agent_id=seeded["care"]["agent_id"],
                    agent_version_id=seeded["care"]["version_id"], channel=channel, status="ended", outcome=outcome,
                    started_at=start, ended_at=start + timedelta(minutes=2), is_eval=is_eval, meta=meta or {})
        s.add(call)
        await s.flush()
        for i, (kind, text, data) in enumerate(events, 1):
            s.add(CallEvent(tenant_id="evergreen-care", call_id=call.id, seq=i, kind=kind, text=text, data=data))
        await s.commit()
        return call.id


async def _score(call_id: str) -> CallScorecard:
    async with sessionmaker()() as s:
        card = await scoring.score(s, await s.get(Call, call_id))
        await s.commit()
        return card


async def _set_eval_settings(seeded, **settings: Any) -> None:  # noqa: ANN001
    async with sessionmaker()() as s:
        v = await s.get(AgentVersion, seeded["care"]["version_id"])
        v.config = {**v.config, "evaluation": {**(v.config.get("evaluation") or {}), **settings}}
        await s.commit()


async def test_scorecard_after_analysis(client, seeded, fake_llm):
    """Covers: SC-01"""
    fake_llm(responder())
    call_id = await _text_call(client, seeded["care"]["agent_id"], "What's the status of my claim?")
    await jobs.drain()
    card = await _card(call_id)
    assert card is not None and card.agent_version_id == seeded["care"]["version_id"] and card.source == "llm"
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == "score_call", Job.payload["call_id"].as_string() == call_id)) == 1
        assert await s.scalar(select(func.count()).select_from(CallScorecard).where(CallScorecard.call_id == call_id)) == 1
    sim = await _manual_call(seeded, [("user", "hi", {})], channel="simulation", is_eval=True)
    async with sessionmaker()() as s:
        await jobs.enqueue(s, "evergreen-care", "score_call", {"call_id": sim})
        await s.commit()
    await jobs.drain()
    assert await _card(sim) is None


def test_checks_from_config():
    """Covers: SC-02"""
    config = {"policy": {"never": ["Give medical advice.", "Quote premiums."], "escalate_when": ["The caller wants to appeal."], "rules": []},
              "skills": [{"name": "Claims", "escalate_when": "The caller disputes a denial."}]}
    checks = {c.key: c for c in scoring.catalogue(config)}
    never = [c for c in checks.values() if c.key.startswith("never.")]
    assert len(never) == 2 and all(c.hard_gate and c.method == "judge" for c in never)
    assert len([k for k in checks if k.startswith("escalate_when.")]) == 2
    assert {"outcome.goal_met", "knowledge.grounded", "safety.phi_before_verification", "responsiveness.latency"} <= set(checks)
    later = {c.key for c in scoring.catalogue({**config, "policy": {**config["policy"], "rules": ["Be brief."]}})}
    assert set(checks) <= later and f"never.{scoring.text_hash('Give medical advice.')}" in later


async def test_phi_before_verification_is_a_hard_fail(client, seeded, fake_llm):
    """Covers: SC-03"""
    def broken_judge(role, messages, tools):  # noqa: ANN001, ANN202
        raise RuntimeError("judge down")

    fake_llm(broken_judge)
    call_id = await _manual_call(seeded, [
        ("user", "What's my claim status?", {}),
        ("tool_call", None, {"name": "get_claim_status", "args": {"claim_id": "C-20931"}}),
        ("tool_result", None, {"name": "get_claim_status", "ok": True, "result": {"status": "paid"}}),
        ("assistant", "It was paid.", {"latency_ms": 500}),
    ])
    card = await _score(call_id)
    v = _verdicts(card)
    assert v["safety.phi_before_verification"] == "fail" and card.hard_fail
    assert v["knowledge.grounded"] == "unknown"  # the judge could not be reached; the code check still decides


async def test_latency_measures(client, seeded):
    """Covers: SC-04"""
    await _set_eval_settings(seeded, latency_p95_ms=2000, judge_sample_pct=0)
    events: list[tuple[str, str | None, dict]] = [("assistant", "Hello", {})]
    for ms in (400, 500, 600, 700, 2500):
        events += [("user", "question", {}), ("assistant", "answer", {"latency_ms": ms})]
    card = await _score(await _manual_call(seeded, events))
    assert card.measures["latency_p50_ms"] == 600 and card.measures["latency_p95_ms"] == 2500
    assert card.measures["first_response_ms"] == 400
    assert _verdicts(card)["responsiveness.latency"] == "fail"


async def test_sampling(client, seeded, fake_llm):
    """Covers: SC-05"""
    fake_llm(responder())
    await _set_eval_settings(seeded, judge_sample_pct=0)
    plain = await _manual_call(seeded, [("user", "hi", {}), ("assistant", "hello", {"latency_ms": 300})])
    escalated = await _manual_call(seeded, [("user", "a person please", {})], outcome="escalated")
    disliked = await _manual_call(seeded, [("user", "hi", {})])
    async with sessionmaker()() as s:
        s.add(Escalation(tenant_id="evergreen-care", call_id=escalated, agent_id=seeded["care"]["agent_id"], reason_category="caller_requested"))
        s.add(CallFeedback(tenant_id="evergreen-care", call_id=disliked, agent_id=seeded["care"]["agent_id"], rating="down"))
        await s.commit()
    card = await _score(plain)
    assert not card.judged and all(c["verdict"] == "not_judged" for c in card.checks if c["method"] == "judge" and c["key"] != "memory.used_correctly")
    assert all(c["verdict"] != "not_judged" for c in card.checks if c["method"] == "code")
    assert (await _score(escalated)).judged and (await _score(disliked)).judged
    assert scoring.sampled("ff" + "0" * 30, 100) and not scoring.sampled("00" + "0" * 30, 0)


async def test_missing_verdict_is_unknown(client, seeded, fake_llm):
    """Covers: SC-06"""
    fake_llm(responder({"outcome.goal_met": {"verdict": "pass", "reason": "done", "seqs": [1]},
                        "knowledge.grounded": {"verdict": "maybe"}}))
    card = await _score(await _manual_call(seeded, [("user", "hi", {})], outcome="escalated"))
    v = _verdicts(card)
    assert v["outcome.goal_met"] == "pass" and v["knowledge.grounded"] == "unknown" and v["tools.right_use"] == "unknown"


async def test_not_applicable_checks_and_score(client, seeded, fake_llm):
    """Covers: SC-07"""
    fake_llm(responder({"outcome.goal_met": {"verdict": "fail", "reason": "no"}, "knowledge.admits_unknown": {"verdict": "n/a"},
                        "memory.used_correctly": {"verdict": "pass"}, "knowledge.grounded": {"verdict": "pass"}}))
    await _set_eval_settings(seeded, judge_sample_pct=100)
    card = await _score(await _manual_call(seeded, [("user", "hi", {}), ("assistant", "hello", {"latency_ms": 300})]))
    v = _verdicts(card)
    assert v["knowledge.admits_unknown"] == "n/a" and v["memory.used_correctly"] == "n/a"
    passes = sum(1 for c in card.checks if c["verdict"] == "pass")
    fails = sum(1 for c in card.checks if c["verdict"] == "fail")
    assert card.score == round(passes / (passes + fails), 4)


async def test_rescored_after_thumbs_down_keeps_reviews(client, seeded, fake_llm):
    """Covers: SC-08, API-08"""
    fake_llm(responder())
    call_id = await _text_call(client, seeded["care"]["agent_id"], "Claim status please")
    await jobs.drain()
    card = await _card(call_id)
    url = f"/api/scorecards/{card.id}/reviews/knowledge.grounded"
    assert (await client.put(url, headers=H, json={"verdict": "fail", "reviewer": "Dana"})).status_code == 200
    r = await client.put(url, headers=H, json={"verdict": "n/a", "note": "no facts", "reviewer": "Dana"})
    assert r.json()["verdict"] == "n/a" and r.json()["judge_verdict"] == "pass"
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(CheckReview).where(CheckReview.scorecard_id == card.id)) == 1
    assert _verdicts(await _card(call_id))["knowledge.grounded"] == "pass"
    code = await client.put(f"/api/scorecards/{card.id}/reviews/tools.succeeded", headers=H, json={"verdict": "pass", "reviewer": "Dana"})
    assert code.status_code == 409 and code.json()["error"] == "code_check"

    before = card.updated_at
    await client.post(f"/api/calls/{call_id}/feedback", headers=H, json={"rating": "down", "comment": "slow"})
    await jobs.drain()
    after = await _card(call_id)
    assert after.id == card.id and after.updated_at > before and after.measures["feedback"] == "down"
    detail = (await client.get(f"/api/calls/{call_id}", headers=H)).json()
    assert detail["scorecard"]["reviews"]["knowledge.grounded"]["verdict"] == "n/a"


def _review(judge: str, human: str) -> CheckReview:
    return CheckReview(judge_verdict=judge, verdict=human, check_key="knowledge.grounded", reviewer="x")


def test_calibration():
    """Covers: SC-09"""
    twenty = [_review("pass", "pass")] * 15 + [_review("fail", "fail")] * 2 + [_review("pass", "fail")] * 3
    cal = score_report.calibration(twenty)
    assert cal["reviews"] == 20 and cal["agreement"] == 0.85 and cal["calibrated"]
    assert cal["catch_rate"] == 0.4 and cal["baseline"] == 0.75
    assert not score_report.calibration(twenty[:19])["calibrated"]


def test_drift():
    """Covers: SC-10"""
    now = utcnow()
    calls, cards = [], {}
    for i in range(40):
        first = i < 20
        call = Call(id=f"c{i:02d}", outcome="resolved", agent_version_id="v",
                    started_at=now - timedelta(days=30 if first else 2, minutes=i))
        ok = (i % 10 != 0) if first else (i % 4 != 0)  # 90 % then 75 %
        cards[call.id] = CallScorecard(call_id=call.id, checks=[{"key": "outcome.goal_met", "verdict": "pass" if ok else "fail"}])
        calls.append(call)
    assert score_report.drift(calls, cards, now) == ["goal_met"]
    assert score_report.drift(calls[:30], cards, now) == []  # fewer than 20 scored calls in the last window


async def test_old_scorecards_keep_their_checks(client, seeded, fake_llm):
    """Covers: SC-11"""
    fake_llm(responder())
    call_id = await _text_call(client, seeded["care"]["agent_id"], "hello")
    await jobs.drain()
    before = (await client.get(f"/api/calls/{call_id}", headers=H)).json()["scorecard"]["checks"]
    agent_id = seeded["care"]["agent_id"]
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    draft["policy"]["never"].append("Discuss competitor plans.")
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})).status_code == 200
    assert (await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "x"})).status_code == 200
    assert (await client.get(f"/api/calls/{call_id}", headers=H)).json()["scorecard"]["checks"] == before


async def test_seeded_history_scores(client, seeded):
    """Covers: SC-12"""
    agent_id = seeded["care"]["agent_id"]
    summary = (await client.get("/api/evaluation/summary", headers=H, params={"agent_id": agent_id, "days": 90})).json()
    v1 = next(v for v in summary["versions"] if v["version"] == 1)
    assert v1["scored"] == 123 and "grounded" in v1["drift"]
    for key, n in (("outcome.goal_met", 3), ("knowledge.grounded", 5)):
        items = (await client.get("/api/evaluation/scorecards", headers=H,
                                  params={"agent_id": agent_id, "days": 90, "check": key, "verdict": "fail"})).json()["items"]
        assert len(items) == n


async def test_retrieval_recorded(client, seeded, fake_llm):
    """Covers: KN-07"""
    fake_llm(responder(realtime=[FakeReply(tool_calls=[("search_knowledge", {"query": "how do I get a replacement ID card"})]),
                                 FakeReply(text="Here is how.")]))
    call_id = await _text_call(client, seeded["care"]["agent_id"], "How do I get a new ID card?")
    detail = (await client.get(f"/api/calls/{call_id}", headers=H)).json()
    result = next(e for e in detail["events"] if e["kind"] == "tool_result" and e["data"]["name"] == "search_knowledge")
    retrieval = result["data"]["retrieval"]
    assert retrieval["query"] == "how do I get a replacement ID card"
    if retrieval["no_answer"]:
        assert retrieval["chunks"] == []
    else:
        assert all(c["chunk_id"] and c["doc_id"] and c["score"] is not None for c in retrieval["chunks"])
        assert {c["chunk_id"] for c in retrieval["chunks"]} == {r["chunk_id"] for r in result["data"]["result"]["results"]}


async def test_evaluation_config_validation(client, seeded):
    """Covers: DM-08"""
    agent_id = seeded["care"]["agent_id"]
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    bad = [
        {"judge_sample_pct": 120},
        {"custom_checks": [{"question": f"Did the agent do thing number {i}?"} for i in range(11)]},
        {"custom_checks": [{"question": "Was the agent polite throughout?", "group": "style"}]},
    ]
    for ev in bad:
        r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**draft, "evaluation": ev}})
        assert r.status_code == 422, ev
    draft.pop("evaluation", None)
    saved = (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})).json()["draft_config"]
    assert saved["evaluation"] == {"judge_sample_pct": 100, "latency_p95_ms": 2000, "custom_checks": []}


async def test_summary_and_draft_checks(client, seeded, fake_llm):
    """Covers: API-09"""
    fake_llm(responder())
    agent_id = seeded["care"]["agent_id"]
    real = await _text_call(client, agent_id, "hi")
    await jobs.drain()
    sim = await _manual_call(seeded, [("user", "hi", {})], channel="simulation", is_eval=True)
    async with sessionmaker()() as s:
        s.add(CallScorecard(tenant_id="evergreen-care", call_id=sim, agent_id=agent_id, agent_version_id=seeded["care"]["version_id"],
                            checks=[], measures={}))
        await s.commit()
    summary = (await client.get("/api/evaluation/summary", headers=H, params={"agent_id": agent_id, "include_seed": False})).json()
    assert sum(v["calls"] for v in summary["versions"]) == 1 and summary["versions"][0]["scored"] == 1
    assert (await _card(real)) is not None

    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    draft["policy"]["never"].append("Promise a refund.")
    await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})
    items = (await client.get(f"/api/agents/{agent_id}/checks", headers=H)).json()["items"]
    item = next(i for i in items if i["key"] == f"never.{scoring.text_hash('Promise a refund.')}")
    assert item["source"] == "config" and item["hard_gate"]
    published = (await client.get(f"/api/agents/{agent_id}/checks", headers=H, params={"source": "published"})).json()["items"]
    assert item["key"] not in {i["key"] for i in published}
    async with sessionmaker()() as s:
        fresh = Agent(tenant_id="evergreen-care", name="New", draft_config={})
        s.add(fresh)
        await s.commit()
        fresh_id = fresh.id
    r = await client.get(f"/api/agents/{fresh_id}/checks", headers=H, params={"source": "published"})
    assert r.status_code == 409 and r.json()["error"] == "not_published"
