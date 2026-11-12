"""Learning actions: fixes verified after they ship, answers only from people, evaluation findings as actions that close
themselves, ranking, suppression, the API.

Covers: LA-01, LA-02, LA-03, LA-04, LA-05, LA-06, LA-07, LA-08, LA-09, SL-15, SL-16, FL-09, DM-13, API-15
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select, text

from tests.test_self_learning import H, _learning, _run_now, fake
from voiceai import db, jobs
from voiceai.db import sessionmaker, utcnow
from voiceai.learning import actions, propose, score_report
from voiceai.learning.analyze import refresh_stats
from voiceai.models import (
    Call, CallAnalysis, CallScorecard, CheckReview, Cluster, Escalation, EvalResult, EvalRun, EvalScenario, FixProposal,
    LearningAction,
)

GOAL = "You want to know if you can extend your cover while abroad."


async def _member(s, agent_id: str, version_id: str, cluster: Cluster | None, *, when, note: str | None = None,  # noqa: ANN001
                  root: str = "missing_knowledge") -> Call:
    call = Call(tenant_id="northgate-health", agent_id=agent_id, agent_version_id=version_id, channel="text", status="ended",
                outcome="escalated", started_at=when, ended_at=when)
    s.add(call)
    await s.flush()
    s.add(Escalation(tenant_id="northgate-health", call_id=call.id, agent_id=agent_id, status="resolved" if note else "waiting",
                     reason_category="caller_requested", resolution_note=note))
    s.add(CallAnalysis(tenant_id="northgate-health", call_id=call.id, agent_id=agent_id, outcome="escalated", root_cause=root,
                       fixable=True, gap_summary="Extending cover abroad", caller_goal=GOAL,
                       resolution_summary="The AI thinks cover cannot be extended.", cluster_id=cluster.id if cluster else None))
    return call


async def _new_cluster(s, agent_id: str, version_id: str, name: str, n: int, *, note: str | None = None,  # noqa: ANN001
                       root: str = "missing_knowledge", days_ago: float = 1) -> Cluster:
    c = Cluster(tenant_id="northgate-health", agent_id=agent_id, name=name, description=name, root_cause=root,
                fixable=True, centroid=[0.0] * 8)
    s.add(c)
    await s.flush()
    for i in range(n):
        await _member(s, agent_id, version_id, c, when=utcnow() - timedelta(days=days_ago, minutes=i), note=note if i == 0 else None, root=root)
    await s.flush()
    await refresh_stats(s, c)
    return c


async def _quiet_seed_clusters(seeded) -> None:  # noqa: ANN001
    async with sessionmaker()() as s:
        for c in (await s.scalars(select(Cluster).where(Cluster.agent_id == seeded["care"]["agent_id"]))).all():
            c.status = "ignored"
        await s.commit()


async def _open(kind: str, key_part: str = "") -> list[LearningAction]:
    async with sessionmaker()() as s:
        return [a for a in (await s.scalars(select(LearningAction).where(LearningAction.kind == kind))).all()
                if a.status == "open" and key_part in a.key]


async def test_fix_not_holding_reopens_the_cluster(client, seeded, fake_llm):
    """Covers: SL-15, LA-01"""
    fake_llm(fake())
    await _learning(seeded, max_proposals_per_night=0)
    await _quiet_seed_clusters(seeded)
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    async with sessionmaker()() as s:
        c = await _new_cluster(s, agent_id, version_id, "Extending cover abroad", 5, note="Extend once, up to 30 days.", days_ago=6)
        c.status = "fixed"
        s.add(FixProposal(tenant_id="northgate-health", agent_id=agent_id, cluster_id=c.id, kind="knowledge_article", title="Extensions",
                          status="approved", decided_at=utcnow() - timedelta(days=3), resulting_version_id=version_id, payload={}))
        await _member(s, agent_id, version_id, c, when=utcnow() - timedelta(days=1))  # one call after the fix
        await s.commit()
        cid = c.id
    first = await _run_now(client)
    async with sessionmaker()() as s:
        assert (await s.get(Cluster, cid)).status == "fixed" and first["summary"]["agents"][agent_id]["reopened"] == 0
        await _member(s, agent_id, version_id, await s.get(Cluster, cid), when=utcnow() - timedelta(hours=2))  # a second one
        await s.commit()
    second = await _run_now(client)
    assert second["summary"]["agents"][agent_id]["reopened"] == 1
    async with sessionmaker()() as s:
        c = await s.get(Cluster, cid)
        assert c.status == "open" and c.reopened_at is not None
    [action] = await _open("fix_not_holding", cid)
    assert action.severity == "high" and action.key == f"fix_not_holding:{cid}"
    async with sessionmaker()() as s:  # fixed again: the next run resolves the action
        (await s.get(Cluster, cid)).status = "fixed"
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
        assert (await s.get(LearningAction, action.id)).status == "resolved"


async def test_answer_needed_then_answer_drafts_from_it(client, seeded, fake_llm):
    """Covers: SL-16, LA-02, FL-09"""
    seen: dict[str, list[str]] = {}
    fake_llm(fake(seen=seen))
    await _learning(seeded, max_proposals_per_night=3)
    await _quiet_seed_clusters(seeded)
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    async with sessionmaker()() as s:
        silent = await _new_cluster(s, agent_id, version_id, "Extending cover abroad", 5)
        noted = await _new_cluster(s, agent_id, version_id, "Pet cover", 5, note="Pets are not covered by the plan.")
        await s.commit()
        silent_id, noted_id = silent.id, noted.id
    run = await _run_now(client)
    drafted = {p["id"] for p in run["summary"]["agents"][agent_id]["proposals"]}
    async with sessionmaker()() as s:
        by_cluster = {p.cluster_id for p in (await s.scalars(select(FixProposal).where(FixProposal.id.in_(drafted)))).all()}
        evidence = await propose.cluster_evidence(s, silent_id)
    assert noted_id in by_cluster and silent_id not in by_cluster  # SL-16
    assert all(e["resolution_note"] == "" for e in evidence)  # FL-09: never the AI's own summary
    assert not any("The AI thinks" in p for p in seen.get("drafting", []))
    r = await client.post(f"/api/insights/clusters/{silent_id}/draft-fix", headers=H)
    assert r.status_code == 409 and r.json()["error"] == "answer_needed"
    [action] = await _open("answer_needed", silent_id)
    assert (await client.post(f"/api/actions/{action.id}/answer", headers=H, json={"answer": "Too short.", "by": "Dana"})).status_code == 422
    answer = "Extend once while abroad, by up to 30 days."
    r = await client.post(f"/api/actions/{action.id}/answer", headers=H, json={"answer": answer, "by": "Dana"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    await jobs.drain()
    async with sessionmaker()() as s:
        assert (await s.get(Cluster, silent_id)).human_answer == answer
        p = await s.scalar(select(FixProposal).where(FixProposal.cluster_id == silent_id))
        assert p is not None and p.status == "ready" and p.latest_eval_run_id
    assert any(answer in prompt for prompt in seen["drafting"])


async def _new_version(client, seeded) -> str:  # noqa: ANN001
    agent_id = seeded["care"]["agent_id"]
    r = await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "for actions"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _scored(s, agent_id: str, version_id: str, checks: list[dict[str, Any]]) -> tuple[Call, CallScorecard]:  # noqa: ANN001
    call = Call(tenant_id="northgate-health", agent_id=agent_id, agent_version_id=version_id, channel="text", status="ended",
                outcome="resolved", started_at=utcnow() - timedelta(days=1), ended_at=utcnow() - timedelta(days=1))
    s.add(call)
    await s.flush()
    card = CallScorecard(tenant_id="northgate-health", call_id=call.id, agent_id=agent_id, agent_version_id=version_id, checks=checks)
    s.add(card)
    await s.flush()
    return call, card


def _check(key: str, verdict: str, method: str = "code") -> dict[str, Any]:
    return {"key": key, "verdict": verdict, "method": method, "hard_gate": False, "text": key}


async def test_check_failing_opens_and_resolves(client, seeded):
    """Covers: LA-03, LA-04"""
    agent_id = seeded["care"]["agent_id"]
    version_id = await _new_version(client, seeded)
    async with sessionmaker()() as s:
        cards = []
        for i in range(12):
            judge = "fail" if i < 3 else ("pass" if i < 10 else "n/a")
            cards.append(await _scored(s, agent_id, version_id, [_check("tools.succeeded", "fail" if i < 4 else "pass"),
                                                                 _check("custom.politeness", judge, "judge")]))
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
    [code] = await _open("check_failing", "tools.succeeded")
    assert code.severity == "medium" and code.evidence["rate"] == 0.33 and len(code.evidence["call_ids"]) == 4
    [review] = await _open("check_failing", "custom.politeness")
    assert review.title.startswith("Review 3 calls") and review.evidence["needs_review"]
    async with sessionmaker()() as s:
        for _, old in cards[1:4]:  # three of the four tool failures pass now: 1 in 12
            card = await s.get(CallScorecard, old.id)
            card.checks = [_check("tools.succeeded", "pass"), *card.checks[1:]]
        for call, card in cards[:3]:  # every listed judge failure gets a review
            s.add(CheckReview(tenant_id="northgate-health", scorecard_id=card.id, call_id=call.id, agent_id=agent_id,
                              check_key="custom.politeness", judge_verdict="fail", verdict="fail", reviewer="Dana"))
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
        assert (await s.get(LearningAction, code.id)).status == "resolved"
        assert (await s.get(LearningAction, review.id)).status == "resolved"


async def test_drift_action(client, seeded, monkeypatch):
    """Covers: LA-05"""
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    drift = {"value": ["goal_met"]}

    async def summary(s, tenant_id, agent, days, include_seed):  # noqa: ANN001, ANN202
        return {"versions": [{"version_id": version_id, "version": 1, "scored": 40, "drift": drift["value"]}]}

    monkeypatch.setattr(score_report, "summary", summary)
    async with sessionmaker()() as s:
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
    [a] = await _open("drift")
    assert a.severity == "high" and a.title == "Goal met drifted on v1"
    drift["value"] = []
    async with sessionmaker()() as s:
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
        assert (await s.get(LearningAction, a.id)).status == "resolved"


async def _suite_run(s, agent_id: str, version_id: str, scenario_id: str, passed: int, when) -> None:  # noqa: ANN001
    run = EvalRun(tenant_id="northgate-health", agent_id=agent_id, kind="suite", baseline_version_id=version_id, target="published",
                  status="done", repeats=3, created_at=when)
    s.add(run)
    await s.flush()
    for k in range(3):
        s.add(EvalResult(tenant_id="northgate-health", eval_run_id=run.id, case_key="sc", case_type="suite", arm="target",
                         scenario_id=scenario_id, repeat=k + 1, scenario={}, expected="resolved", passed=k < passed, failures=[], judge={}))


async def test_scenario_failing_dismiss_and_api(client, seeded):
    """Covers: LA-06, LA-07, API-15"""
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    async with sessionmaker()() as s:
        sc = await s.scalar(select(EvalScenario).where(EvalScenario.agent_id == agent_id, EvalScenario.enabled.is_(True)))
        await _suite_run(s, agent_id, version_id, sc.id, 1, utcnow() - timedelta(hours=2))
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
        sid = sc.id
    [a] = await _open("scenario_failing", sid)
    assert a.title.endswith("(1/3, flaky)")
    async with sessionmaker()() as s:  # a later run passes it: resolved
        await _suite_run(s, agent_id, version_id, sid, 3, utcnow())
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
        assert (await s.get(LearningAction, a.id)).status == "resolved"
        await _suite_run(s, agent_id, version_id, sid, 0, utcnow() + timedelta(minutes=1))  # failing again: a new action
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
    [b] = await _open("scenario_failing", sid)
    r = await client.post(f"/api/actions/{b.id}/dismiss", headers=H, json={"by": "Dana", "note": "Known simulator issue"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed" and r.json()["closed_by"] == "Dana" and r.json()["closed_at"]
    assert (await client.post(f"/api/actions/{b.id}/dismiss", headers=H, json={"by": "Dana"})).status_code == 409
    assert (await client.post(f"/api/actions/{b.id}/answer", headers=H, json={"answer": "x" * 30, "by": "Dana"})).status_code == 409
    assert b.id not in {x["id"] for x in (await client.get("/api/insights/actions", headers=H)).json()["items"]}
    assert b.id in {x["id"] for x in (await client.get("/api/insights/actions?status=all", headers=H)).json()["items"]}
    assert (await client.post(f"/api/actions/{b.id}/done", headers={"X-Tenant-Id": "northgate-sandbox"}, json={})).status_code == 404
    async with sessionmaker()() as s:  # LA-07: the same finding does not reopen inside the snooze window
        await actions.derive(s, "northgate-health", agent_id)
        await s.commit()
    assert await _open("scenario_failing", sid) == []


async def test_actions_are_ranked(client, seeded):
    """Covers: LA-08"""
    agent_id = seeded["care"]["agent_id"]
    async with sessionmaker()() as s:
        for key, severity, impact in (("m-low", "medium", 1), ("h-low", "high", 2), ("m-high", "medium", 9), ("h-high", "high", 50)):
            s.add(LearningAction(tenant_id="northgate-health", agent_id=agent_id, kind="drift", key=key, severity=severity, title=key, impact=impact))
        await s.commit()
    items = (await client.get("/api/insights/actions", headers=H)).json()["items"]
    keys = [i["key"] for i in items if i["key"] in ("m-low", "h-low", "m-high", "h-high")]
    assert keys == ["h-high", "h-low", "m-high", "m-low"]
    assert items[0]["agent_name"]


async def test_fix_report_says_the_fix_held(client, seeded):
    """Covers: LA-09"""
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    async with sessionmaker()() as s:
        c = await _new_cluster(s, agent_id, version_id, "Extending cover abroad", 6, note="Extend once.", days_ago=12)
        c.status = "fixed"
        s.add(FixProposal(tenant_id="northgate-health", agent_id=agent_id, cluster_id=c.id, kind="knowledge_article", title="Extensions",
                          status="approved", decided_at=utcnow() - timedelta(days=10), resulting_version_id=version_id, payload={}))
        await s.commit()
        cid = c.id
    detail = (await client.get(f"/api/insights/clusters/{cid}", headers=H)).json()
    assert detail["fix"]["before_per_week"] == 1.5 and detail["fix"]["after_per_week"] == 0 and detail["fix"]["held"] is True
    assert detail["needs_answer"] is False
    listed = next(c for c in (await client.get("/api/insights/clusters", headers=H)).json()["items"] if c["id"] == cid)
    assert listed["fix"]["held"] is True


async def test_old_database_gains_the_cluster_columns(tmp_path: Path):
    """Covers: DM-13"""
    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'old.sqlite').as_posix()}")
    async with db.engine().begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY, name VARCHAR(200), industry VARCHAR(100), created_at DATETIME)")
        await conn.exec_driver_sql(
            "CREATE TABLE clusters (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id), agent_id VARCHAR(32), "
            "name VARCHAR(200), description TEXT, root_cause VARCHAR(32), fixable BOOLEAN, centroid JSON, call_count INTEGER, "
            "escalation_count INTEGER, first_seen_at DATETIME, last_seen_at DATETIME, status VARCHAR(16), snoozed_until DATETIME, "
            "created_at DATETIME NOT NULL, updated_at DATETIME)")
        await conn.exec_driver_sql("INSERT INTO tenants VALUES ('t', 'T', '', '2026-10-01 00:00:00')")
        await conn.exec_driver_sql("INSERT INTO clusters VALUES ('c1', 't', 'a', 'Gap', '', 'missing_knowledge', 1, '[0.0]', 5, 5, NULL, NULL, "
                                   "'fixed', NULL, '2026-10-01 00:00:00', NULL)")
    await db.init_db()
    async with db.engine().begin() as conn:
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("clusters")})
        assert {"human_answer", "human_answer_by", "reopened_at"} <= cols
        assert (await conn.execute(text("SELECT status, human_answer, reopened_at FROM clusters"))).one() == ("fixed", None, None)
    await db.engine().dispose()

