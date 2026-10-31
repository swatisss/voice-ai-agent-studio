"""Test suites: scenarios, expectations, runs with repeats, targets, triggers, scenario memory and personas.

Covers: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06, TEST-07, TEST-08, TEST-09, TEST-10, SC-01
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from voiceai import jobs
from voiceai.db import sessionmaker
from voiceai.events import bus
from voiceai.learning import test_suites
from voiceai.learning.evaluate import CALLER_STYLES
from voiceai.llm.gateway import FakeReply
from voiceai.models import (
    Agent, AgentVersion, Call, CallEvent, CallScorecard, EvalResult, EvalRun, Job, MemberMemory, MemoryEvent,
)

H = {"X-Tenant-Id": "evergreen-care"}
MARIA = {"name": "Maria Lopez", "member_id": "482913", "date_of_birth": "1986-04-12"}
VERIFY = ("verify_member", {"member_id": "482913", "date_of_birth": "1986-04-12"})


def fake(*, goal_fails: dict[str, int] | None = None, verify_first: bool = False, seen: dict[str, list[str]] | None = None):  # noqa: ANN201
    """Simulator: one line then hang up. Agent: optionally verifies on its first reply, then answers. Judge: every
    check passes, except `outcome.goal_met` fails the first n times a goal containing a key of `goal_fails` is judged."""
    fails = dict(goal_fails or {})
    seen = seen if seen is not None else {}

    def r(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:  # noqa: ANN401
        prompt = messages[-1]["content"] if messages else ""
        seen.setdefault(role, []).append(prompt if role != "realtime" else messages[0]["content"])
        if role == "simulator":
            return "[HANGUP]" if "Caller:" in prompt else "Hello, I have a question."
        if role == "realtime":
            already = any(m.get("role") == "tool" for m in messages)
            if verify_first and not already:
                return FakeReply(tool_calls=[VERIFY])
            return FakeReply(text="Okay, that's done.")
        if role == "judge":
            keys = [line.split(":", 1)[0] for line in prompt.split("Checks:\n", 1)[1].split("\n\nReturn JSON", 1)[0].splitlines()]
            checks = {k: {"verdict": "pass", "reason": "ok"} for k in keys}
            for marker, n in fails.items():
                if marker in prompt and n > 0:
                    fails[marker] = n - 1
                    checks["outcome.goal_met"] = {"verdict": "fail", "reason": "not met"}
            return {"outcome": "resolved", "goal_met": True, "grounded": True, "policy_violations": [], "notes": "", "checks": checks}
        if role == "analysis":
            return {"outcome": "resolved", "intent": "x", "root_cause": "none", "gap_summary": "", "caller_goal": "x",
                    "resolution_summary": "", "sentiment_start": "neutral", "sentiment_end": "neutral"}
        raise AssertionError(role)

    return r


async def _scenario(client, agent_id: str, **body: Any) -> dict:  # noqa: ANN001
    data = {"name": "Scenario", "caller_goal": "You want to check something simple.", **body}
    r = await client.post(f"/api/agents/{agent_id}/scenarios", headers=H, json=data)
    assert r.status_code == 200, r.text
    return r.json()


async def _run(client, agent_id: str, **body: Any) -> dict:  # noqa: ANN001
    r = await client.post(f"/api/agents/{agent_id}/test-runs", headers=H, json=body)
    assert r.status_code == 200, r.text
    await jobs.drain()
    return (await client.get(f"/api/test-runs/{r.json()['eval_run_id']}", headers=H)).json()


def _events(*items: tuple[str, str | None, dict]) -> list[CallEvent]:
    return [CallEvent(seq=i, kind=k, text=t, data=d) for i, (k, t, d) in enumerate(items, 1)]


def _tool(name: str, args: dict, ok: bool, result: dict, cid: str) -> list[tuple[str, None, dict]]:
    return [("tool_call", None, {"tool_call_id": cid, "name": name, "args": args}),
            ("tool_result", None, {"tool_call_id": cid, "name": name, "ok": ok, "result": result})]


PASSING = [{"key": "outcome.goal_met", "verdict": "pass", "hard_gate": False, "text": ""}]


def test_required_tools_and_arguments():
    """Covers: TEST-01"""
    sc = {"expected": "resolved", "required_tools": [{"name": "get_claim_status", "args": {"claim_id": "C-20931"}}]}
    wrong = _events(*_tool("get_claim_status", {"claim_id": "C-20977"}, True, {"status": "processing"}, "a"))
    failures = test_suites.check(sc, wrong, "resolved", PASSING, False)
    assert failures == ["get_claim_status was never called with claim_id=C-20931"]
    right = _events(*_tool("get_claim_status", {"claim_id": "c-20931 "}, True, {"status": "paid"}, "b"))
    assert test_suites.check(sc, right, "resolved", PASSING, False) == []
    failed = _events(*_tool("get_claim_status", {"claim_id": "C-20931"}, False, {"error": "timeout"}, "c"))
    assert test_suites.check(sc, failed, "resolved", PASSING, False) != []


def test_forbidden_tools_and_expected_results():
    """Covers: TEST-02"""
    forbid = {"expected": "resolved", "forbidden_tools": ["submit_claim"]}
    ev = _events(*_tool("submit_claim", {}, True, {"claim_id": "C-1"}, "a"))
    assert test_suites.check(forbid, ev, "resolved", PASSING, False) == ["submit_claim was called, but it is forbidden"]
    expect = {"expected": "resolved", "expected_results": [{"tool": "request_document", "field": "status", "equals": "queued"}]}
    ok = _events(*_tool("request_document", {}, True, {"request_id": "DOC-1", "status": "queued"}, "b"))
    assert test_suites.check(expect, ok, "resolved", PASSING, False) == []
    other = _events(*_tool("request_document", {}, True, {"status": "sent"}, "c"))
    assert test_suites.check(expect, other, "resolved", PASSING, False) == ["No request_document result had status = queued"]
    gate = [{"key": "never.x", "verdict": "fail", "hard_gate": True, "text": "Did the agent avoid: \"x\"?"}, *PASSING]
    assert test_suites.check({"expected": "escalated"}, [], "resolved", gate, True) == [
        "Expected escalated, got resolved", "Hard fail: Did the agent avoid: \"x\"?"]


async def test_run_repeats_and_summary(client, seeded, fake_llm):
    """Covers: TEST-03, SC-01"""
    fake_llm(fake(goal_fails={"beta": 1}))
    agent_id = seeded["care"]["agent_id"]
    a = await _scenario(client, agent_id, name="A", caller_goal="You want to ask about alpha things.")
    b = await _scenario(client, agent_id, name="B", caller_goal="You want to ask about beta things.")
    run = await _run(client, agent_id, scenario_ids=[a["id"], b["id"]], repeats=3)
    s = run["summary"]
    assert run["status"] == "done" and s["pass_all"] == 1 and s["pass_any"] == 2 and s["pass_rate"] == 0.8333
    assert s["by_scenario"] == {a["id"]: {"passed": 3, "of": 3}, b["id"]: {"passed": 2, "of": 3}}
    assert len(run["results"]) == 6 and all(r["scorecard"] is not None for r in run["results"])
    async with sessionmaker()() as session:
        cards = (await session.scalars(select(CallScorecard).join(Call, Call.id == CallScorecard.call_id).where(Call.is_eval.is_(True)))).all()
        assert len(cards) == 6 and all(c.judged for c in cards)
        assert await session.scalar(select(func.count()).select_from(Job).where(Job.kind == "score_call")) == 0  # SC-01


async def test_draft_target(client, seeded, fake_llm):
    """Covers: TEST-04"""
    fake_llm(fake())
    agent_id = seeded["care"]["agent_id"]
    sc = await _scenario(client, agent_id, name="Draft check")
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    draft["policy"]["never"].append("Promise a refund.")
    saved = (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})).json()["draft_config"]
    async with sessionmaker()() as session:
        versions = await session.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent_id))
    run = await _run(client, agent_id, target="draft", scenario_ids=[sc["id"]], repeats=1)
    from voiceai.learning.scoring import text_hash
    async with sessionmaker()() as session:
        card = await session.scalar(select(CallScorecard).where(CallScorecard.call_id == run["results"][0]["call_id"]))
        assert f"never.{text_hash('Promise a refund.')}" in {c["key"] for c in card.checks}
        assert await session.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent_id)) == versions
    assert (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"] == saved


async def test_run_refusals(client, seeded, fake_llm):
    """Covers: TEST-05"""
    fake_llm(fake())
    agent_id = seeded["care"]["agent_id"]
    first = await client.post(f"/api/agents/{agent_id}/test-runs", headers=H, json={"repeats": 1})
    assert first.status_code == 200
    again = await client.post(f"/api/agents/{agent_id}/test-runs", headers=H, json={"repeats": 1})
    assert again.status_code == 409 and again.json()["error"] == "run_in_progress"
    await jobs.drain()
    async with sessionmaker()() as session:
        fresh = Agent(tenant_id="evergreen-care", name="Fresh", draft_config={})
        session.add(fresh)
        await session.commit()
    r = await client.post(f"/api/agents/{fresh.id}/test-runs", headers=H, json={})
    assert r.status_code == 409 and r.json()["error"] == "not_published"
    claims = seeded["claims"]["agent_id"]
    for item in (await client.get(f"/api/agents/{claims}/scenarios", headers=H)).json()["items"]:
        await client.put(f"/api/scenarios/{item['id']}", headers=H, json={"enabled": False})
    r = await client.post(f"/api/agents/{claims}/test-runs", headers=H, json={})
    assert r.status_code == 422 and r.json()["error"] == "no_scenarios"


async def test_scenario_memory(client, seeded, fake_llm):
    """Covers: TEST-06"""
    seen: dict[str, list[str]] = {}
    fake_llm(fake(verify_first=True, seen=seen))
    agent_id = seeded["care"]["agent_id"]
    async with sessionmaker()() as session:
        mems = await session.scalar(select(func.count()).select_from(MemberMemory))
        mem_events = await session.scalar(select(func.count()).select_from(MemoryEvent))
    sc = await _scenario(client, agent_id, name="Memory", caller_profile=MARIA, memory=["Prefers documents by email"])
    run = await _run(client, agent_id, scenario_ids=[sc["id"]], repeats=1)
    call_id = run["results"][0]["call_id"]
    assert any("Prefers documents by email" in p for p in seen["realtime"])
    async with sessionmaker()() as session:
        loaded = await session.scalar(select(CallEvent).where(CallEvent.call_id == call_id, CallEvent.text == "Memory loaded"))
        assert loaded is not None and loaded.data["scenario_memory"] == 1
        assert await session.scalar(select(func.count()).select_from(MemberMemory)) == mems
        assert await session.scalar(select(func.count()).select_from(MemoryEvent)) == mem_events
        assert await session.scalar(select(func.count()).select_from(Job).where(Job.kind == "extract_memory")) == 0


async def test_personas_reach_the_simulator(client, seeded, fake_llm):
    """Covers: TEST-07"""
    seen: dict[str, list[str]] = {}
    fake_llm(fake(seen=seen))
    agent_id = seeded["care"]["agent_id"]
    sc = await _scenario(client, agent_id, name="Tricky", persona="adversarial")
    await _run(client, agent_id, scenario_ids=[sc["id"]], repeats=1)
    assert any(f"How you behave: {CALLER_STYLES['adversarial']}" in p for p in seen["simulator"])
    assert set(CALLER_STYLES) == {"calm", "confused", "impatient", "adversarial"}
    assert CALLER_STYLES["adversarial"].startswith("Tries to get member information before verifying")


async def test_publish_starts_a_run(client, seeded, fake_llm):
    """Covers: TEST-08"""
    fake_llm(fake())
    agent_id = seeded["care"]["agent_id"]
    async with sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(EvalRun).where(EvalRun.kind == "suite")) == 0  # the seeder starts none
    r = await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "x"})
    async with sessionmaker()() as session:
        runs = (await session.scalars(select(EvalRun).where(EvalRun.agent_id == agent_id, EvalRun.kind == "suite"))).all()
        assert len(runs) == 1 and runs[0].trigger == "publish" and runs[0].baseline_version_id == r.json()["id"]
    await jobs.drain()
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    draft.setdefault("evaluation", {})["test_on_publish"] = False
    await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})
    await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "y"})
    async with sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(EvalRun).where(EvalRun.agent_id == agent_id, EvalRun.kind == "suite")) == 1


async def test_progress_events_and_hidden_calls(client, seeded, fake_llm):
    """Covers: TEST-09"""
    fake_llm(fake())
    agent_id = seeded["care"]["agent_id"]
    sc = await _scenario(client, agent_id, name="Events")
    sub = bus.subscribe("evergreen-care", {"evaluation"})
    run = await _run(client, agent_id, scenario_ids=[sc["id"]], repeats=2)
    got = []
    while not sub.queue.empty():
        got.append(sub.queue.get_nowait())
    progress = [e for e in got if e["type"] == "test_run.progress"]
    finished = [e for e in got if e["type"] == "test_run.finished"]
    assert [e["data"]["done"] for e in progress] == [1, 2] and all(e["data"]["total"] == 2 for e in progress)
    assert len(finished) == 1 and finished[0]["data"]["summary"]["pass_all"] == 1
    listed = {c["id"] for c in (await client.get("/api/calls", headers=H)).json()["items"]}
    assert not listed & {r["call_id"] for r in run["results"]}
    summary = (await client.get("/api/evaluation/summary", headers=H, params={"agent_id": agent_id, "include_seed": False})).json()
    assert sum(v["calls"] for v in summary["versions"]) == 0


async def test_results_keep_the_scenario_as_it_ran(client, seeded, fake_llm):
    """Covers: TEST-10"""
    fake_llm(fake())
    agent_id = seeded["care"]["agent_id"]
    sc = await _scenario(client, agent_id, name="Before", caller_goal="You want to ask about the original thing.")
    run = await _run(client, agent_id, scenario_ids=[sc["id"]], repeats=1)
    await client.put(f"/api/scenarios/{sc['id']}", headers=H, json={"name": "After", "caller_goal": "You want to ask about a new thing."})
    again = (await client.get(f"/api/test-runs/{run['id']}", headers=H)).json()
    assert again["results"][0]["scenario"]["name"] == "Before"
    bad = await client.post(f"/api/agents/{agent_id}/scenarios", headers=H,
                            json={"name": "Bad", "caller_goal": "You want something odd.", "forbidden_tools": ["launch_rocket"]})
    assert bad.status_code == 422 and bad.json()["error"] == "unknown_tool"
    dup = await client.post(f"/api/agents/{agent_id}/scenarios", headers=H, json={"name": "After", "caller_goal": "You want another thing."})
    assert dup.status_code == 409 and dup.json()["error"] == "name_taken"
    async with sessionmaker()() as session:
        assert (await session.get(EvalResult, (await session.scalar(select(EvalResult.id).where(EvalResult.eval_run_id == run["id"]))))).scenario["name"] == "Before"
