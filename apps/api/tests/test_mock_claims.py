"""Claim first notice and required documents in the mock insurance API. Covers: MOCK-13, MOCK-14"""
from __future__ import annotations

from datetime import timedelta

from voiceai.mock import data

AISHA = {"X-Member-Ref": "EVG-725031"}
HEALTH = "HP-100877"


def _notice(**over):  # noqa: ANN003, ANN202
    body = {
        "policy_id": HEALTH, "claim_type": "urgent_care", "service_date": (data.today() - timedelta(days=1)).isoformat(),
        "provider": "Harbor Urgent Care", "description": "Sprained ankle, urgent care visit", "estimated_amount": 150,
    }
    return {**body, **over}


async def test_first_notice_creates_a_claim_and_rejects_bad_requests(client):
    """Covers: MOCK-13"""
    r = await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice())
    assert r.status_code == 200
    body = r.json()
    assert body["claim_id"] == "C-90001" and body["status"] == "received" and body["expected_decision_days"] == 30
    assert [d["document"] for d in body["required_documents"]][:2] == ["Itemized provider bill", "Proof of payment"]
    listed = (await client.get("/mock/healthcare/claims", headers=AISHA)).json()["claims"]
    assert "C-90001" in [c["claim_id"] for c in listed]
    detail = (await client.get("/mock/healthcare/claims/C-90001", headers=AISHA)).json()
    assert detail["status"] == "received" and detail["provider"] == "Harbor Urgent Care"

    dup = await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice())
    assert dup.status_code == 409 and dup.json()["error"] == "duplicate_claim" and dup.json()["existing_claim_id"] == "C-90001"
    mismatch = await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice(claim_type="motor_glass"))
    assert mismatch.status_code == 409 and mismatch.json()["error"] == "claim_type_mismatch"
    future = (data.today() + timedelta(days=2)).isoformat()
    assert (await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice(service_date=future))).status_code == 422
    assert (await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice(claim_type="vet"))).status_code == 422
    assert (await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice(description="x"))).status_code == 422
    assert (await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice(policy_id="MP-200415"))).status_code == 404
    assert (await client.post("/mock/insurance/claims/first-notice", json=_notice())).status_code == 401


async def test_new_claims_reset_with_the_business_data(client):
    """Covers: MOCK-13"""
    assert (await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice())).status_code == 200
    data.reset()
    assert "C-90001" not in data.CLAIMS
    again = await client.post("/mock/insurance/claims/first-notice", headers=AISHA, json=_notice())
    assert again.json()["claim_id"] == "C-90001"


async def test_requirements_need_no_member_and_cover_every_type(client):
    """Covers: MOCK-14"""
    collision = (await client.get("/mock/insurance/claims/requirements", params={"claim_type": "motor_collision"})).json()
    assert [d["document"] for d in collision["documents"]] == [
        "Repair estimate or invoice", "Photos of all vehicles involved", "The other party's details", "Police report number",
    ]
    assert collision["where_to_send"]
    for kind in data.CLAIM_TYPES:
        r = (await client.get("/mock/insurance/claims/requirements", params={"claim_type": kind})).json()
        assert r["claim_type"] == kind and r["documents"]
    bad = await client.get("/mock/insurance/claims/requirements", params={"claim_type": "vet"})
    assert bad.status_code == 422 and bad.json()["error"] == "invalid_claim_type"
