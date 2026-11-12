"""Compliance evidence: the controls from the spec, the report script, the audit trail on a call.

Covers: CMP-01, CMP-02, CMP-03
"""
from __future__ import annotations

import importlib.util
from tests.test_self_learning import H, _ready_proposal
from voiceai import compliance
from voiceai.config import REPO_DIR
from voiceai.db import sessionmaker
from voiceai.models import Call


def _script():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("compliance_check", REPO_DIR / "scripts" / "compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_evidence_without_a_report(client, monkeypatch, tmp_path):
    """Covers: CMP-01"""
    monkeypatch.setattr(compliance, "REPORT", tmp_path / "none.json")
    r = await client.get("/api/compliance/evidence")
    assert r.status_code == 200
    body = r.json()
    ids = [c["id"] for c in body["controls"]]
    assert ids == [f"C{i}" for i in range(1, 16)]  # C15: contact tools (CP-0040)
    c1 = body["controls"][0]
    assert c1["enforcement"] == "code" and "164.514(h)" in c1["reference"] and "TS-01" in [e["id"] for e in c1["evidence"]]
    assert all(e["status"] == "not_run" for c in body["controls"] for e in c["evidence"])
    c14 = next(c for c in body["controls"] if c["id"] == "C14")
    assert c14["status"] == "process" and c14["evidence"] == []
    assert any("Business Associate" in g for g in body["gaps"])
    assert body["report"] is None


def test_report_runs_only_evidence_tests_and_marks_a_failure():
    """Covers: CMP-02"""
    script = _script()
    ids = script.evidence_ids()
    tests = script.citing_tests()
    assert "TS-01" in ids and tests["TS-01"]
    ran: list[str] = []
    failing = tests["TS-01"][0]

    def runner(nodes: list[str]) -> dict[str, bool]:
        ran.extend(nodes)
        return {n: n != failing for n in nodes}

    report = script.build_report(ids, tests, runner=runner, commit="abc123")
    evidence_nodes = {n for i in ids for n in tests.get(i, [])}
    assert set(ran) == evidence_nodes  # nothing else ran
    assert not any("test_design_tokens" in n for n in ran)
    assert report["ids"]["TS-01"]["failed"] >= 1
    out = compliance.evidence(report)
    by_id = {c["id"]: c for c in out["controls"]}
    failed = [c for c in out["controls"] if c["status"] == "failed"]
    assert by_id["C1"]["status"] == "failed" and all("TS-01" in [e["id"] for e in c["evidence"]] for c in failed)
    assert by_id["C5"]["status"] in ("passed", "not_run") and by_id["C14"]["status"] == "process"
    assert out["report"] == {"generated_at": report["generated_at"], "commit": "abc123"}
    assert all(e["status"] in ("passed", "no_test") for e in by_id["C5"]["evidence"])


async def test_call_shows_who_published_its_version(client, seeded):
    """Covers: CMP-03"""
    pid = await _ready_proposal(seeded, "policy_rule", {"rule": "Offer the member portal."})
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Dana"})
    version_id = r.json()["version"]["id"]
    agent_id = seeded["care"]["agent_id"]
    async with sessionmaker()() as s:
        fixed = Call(tenant_id="northgate-health", agent_id=agent_id, agent_version_id=version_id, channel="text", status="ended")
        built = Call(tenant_id="northgate-health", agent_id=agent_id, agent_version_id=seeded["care"]["version_id"], channel="text", status="ended")
        s.add_all([fixed, built])
        await s.commit()
        fixed_id, built_id = fixed.id, built.id
    info = (await client.get(f"/api/calls/{fixed_id}", headers=H)).json()["version_info"]
    assert info["version"] == r.json()["version"]["version"] and info["published_by"] == "Studio" and info["published_at"]
    assert info["change_note"].startswith("Fix:")
    sp = info["source_proposal"]
    assert sp["id"] == pid and sp["title"] == "t" and sp["decided_by"] == "Dana" and sp["decided_at"] and sp["cluster_id"]
    seeded_info = (await client.get(f"/api/calls/{built_id}", headers=H)).json()["version_info"]
    assert seeded_info["source_proposal"] is None and seeded_info["published_by"] is None

