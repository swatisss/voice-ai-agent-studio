"""Mock cover check, specialist finder and pre-authorisation. Covers: MOCK-24, MOCK-25, MOCK-26"""
from __future__ import annotations

from datetime import date, timedelta

from voiceai.mock import data

SARAH = {"X-Member-Ref": "NGH-410237"}
DAVID = {"X-Member-Ref": "NGH-522918"}
EMMA = {"X-Member-Ref": "NGH-638405"}
RAJ = {"X-Member-Ref": "NGH-714560"}
TOM = {"X-Member-Ref": "NGH-805193"}


async def _check(client, who, policy_id, condition, treatment="consultation"):  # noqa: ANN001, ANN202
    r = await client.get(f"/mock/insurance/policies/{policy_id}/eligibility", headers=who, params={"condition": condition, "treatment": treatment})
    assert r.status_code == 200
    return r.json()


async def test_cover_check(client):
    """Covers: MOCK-24"""
    sarah = await _check(client, SARAH, "PMI-300101", "knee pain", "MRI scan")
    assert sarah["covered"] is True and sarah["referral_needed"] is False and sarah["direct_access_category"]
    assert any("pre-treatment form" in f for f in sarah["forms_needed"])
    raj = await _check(client, RAJ, "PMI-300452", "back pain")
    assert raj["covered"] is False and "excluded" in raj["reason"]
    emma_migraine = await _check(client, EMMA, "PMI-300377", "migraine")
    assert emma_migraine["covered"] is False and "Moratorium" in emma_migraine["reason"]
    david = await _check(client, DAVID, "PMI-300214", "knee osteoarthritis", "knee replacement")
    assert david["covered"] is False and "missed" in david["reason"]
    tom_consult = await _check(client, TOM, "PMI-300519", "knee pain", "consultation")
    assert tom_consult["covered"] is False and "Essentials" in tom_consult["reason"]
    tom_surgery = await _check(client, TOM, "PMI-300519", "knee osteoarthritis", "knee replacement")
    assert tom_surgery["covered"] is True and tom_surgery["referral_needed"] is True
    emma = await _check(client, EMMA, "PMI-300377", "shoulder pain", "consultation")
    assert emma["outpatient_remaining"] == 360
    r = await client.get("/mock/insurance/policies/CSH-400204/eligibility", headers=EMMA, params={"condition": "knee pain"})
    assert r.status_code == 409 and r.json()["error"] == "not_applicable"


async def test_specialist_finder(client):
    """Covers: MOCK-25"""
    params = {"condition": "knee pain", "postcode": "LS6 2AB", "policy_id": "PMI-300101"}
    body = (await client.get("/mock/healthcare/specialists", headers=SARAH, params=params)).json()
    assert body["specialty"] == "orthopaedics" and body["hospital_list"] == "extended"
    rows = body["specialists"]
    ids = [s["specialist_id"] for s in rows]
    assert 1 <= len(rows) <= 3
    by_id = {s["id"]: s for s in data.SPECIALISTS}
    assert all(by_id[i]["specialty"] == "orthopaedics" and "extended" in by_id[i]["lists"] for i in ids)
    leeds = [by_id[i]["area"] == "LS" for i in ids]
    assert leeds[0] and leeds == sorted(leeds, reverse=True)  # Leeds ones first
    others = [s["fee_assured"] for s in rows if by_id[s["specialist_id"]]["area"] != "LS"]
    assert others == sorted(others, reverse=True)  # then fee-assured before not fee-assured
    assert ids == ["CN-101", "CN-102", "CN-104"]
    wide = (await client.get("/mock/healthcare/specialists", headers=SARAH, params={"specialty": "orthopaedics", "policy_id": "PMI-300101"})).json()
    assert "CN-106" not in [s["specialist_id"] for s in wide["specialists"]]  # London Premium only
    r = await client.get("/mock/healthcare/specialists", params={"postcode": "LS6 2AB"})
    assert r.status_code == 422


def _pre_auth(**over):  # noqa: ANN003, ANN202
    body = {"policy_id": "PMI-300101", "condition": "knee pain", "treatment": "consultation", "referral": "direct_access",
            "specialist_id": "CN-101", "symptoms_started": "two weeks ago"}
    return {**body, **over}


async def test_pre_authorisation(client):
    """Covers: MOCK-26"""
    r = await client.post("/mock/healthcare/pre-authorisations", headers=SARAH, json=_pre_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["pre_auth_code"] == "PA-502001" and body["excess_to_pay"] == 0
    assert date.fromisoformat(body["valid_through"]) == data.today() + timedelta(days=90)
    r = await client.post("/mock/healthcare/pre-authorisations", headers=SARAH, json=_pre_auth(treatment="knee arthroscopy"))
    assert r.status_code == 200 and r.json()["status"] == "pending"
    r = await client.post("/mock/healthcare/pre-authorisations", headers=RAJ,
                          json=_pre_auth(policy_id="PMI-300452", condition="back pain", specialist_id=None))
    assert r.status_code == 409 and r.json()["error"] == "not_covered"
    r = await client.post("/mock/healthcare/pre-authorisations", headers=TOM,
                          json=_pre_auth(policy_id="PMI-300519", condition="knee osteoarthritis", treatment="knee replacement",
                                         referral="none", specialist_id=None))
    assert r.status_code == 409 and r.json()["error"] == "referral_needed"
    r = await client.post("/mock/healthcare/pre-authorisations", headers=SARAH, json=_pre_auth(symptoms_started=None))
    assert r.status_code == 422
    r = await client.post("/mock/healthcare/pre-authorisations", headers=SARAH, json=_pre_auth(specialist_id="CN-106"))
    assert r.status_code == 409 and r.json()["error"] == "specialist_not_on_list"
    r = await client.post("/mock/healthcare/pre-authorisations", headers=EMMA,
                          json=_pre_auth(policy_id="PMI-300377", condition="shoulder pain", specialist_id="CN-103"))
    assert r.status_code == 200 and r.json()["shortfall_warning"]
