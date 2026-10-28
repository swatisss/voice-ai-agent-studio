"""Mock healthcare API. Covers: MOCK-01, MOCK-02, MOCK-03, MOCK-04, MOCK-15, MOCK-16, MOCK-17"""
from __future__ import annotations


async def test_verify_normalizes_id_and_dob(client):
    """Covers: MOCK-01"""
    r = await client.post("/mock/healthcare/verify", json={"member_id": "482913", "date_of_birth": "April 12, 1986"})
    assert r.json() == {"verified": True, "member_ref": "EVG-482913", "first_name": "Maria", "plan_name": "Evergreen Silver PPO"}
    r = await client.post("/mock/healthcare/verify", json={"member_id": "evg 482913", "date_of_birth": "04/12/1986"})
    assert r.json()["verified"] is True
    r = await client.post("/mock/healthcare/verify", json={"member_id": "482913", "date_of_birth": "1986-04-13"})
    assert r.json()["verified"] is False


async def test_claim_of_other_member_is_404(client):
    """Covers: MOCK-02"""
    r = await client.get("/mock/healthcare/claims/C-31544", headers={"X-Member-Ref": "EVG-482913"})
    assert r.status_code == 404
    r = await client.get("/mock/healthcare/claims/c20931", headers={"X-Member-Ref": "EVG-482913"})
    assert r.status_code == 200 and r.json()["member_responsibility"] == 35.0


async def test_benefits_require_member_header(client):
    """Covers: MOCK-03"""
    r = await client.get("/mock/healthcare/benefits")
    assert r.status_code == 401 and r.json()["error"] == "member_not_verified"
    r = await client.get("/mock/healthcare/benefits", headers={"X-Member-Ref": "EVG-482913"})
    assert r.json()["deductible"] == {"individual": 1500, "met": 850, "remaining": 650}


async def test_provider_search_orders_exact_zip_first(client):
    """Covers: MOCK-04"""
    r = await client.get("/mock/healthcare/providers", params={"specialty": "derm", "zip": "94110"})
    assert r.json()["providers"][0]["practice"] == "Mission Dermatology"


async def test_identify_by_registered_number(client):
    """Covers: MOCK-15"""
    r = await client.post("/mock/healthcare/identify", json={"phone": "+12025550141"})
    assert r.json() == {"matched": True, "member_ref": "EVG-482913", "first_name": "Maria"}
    assert (await client.post("/mock/healthcare/identify", json={"phone": "+12025550199"})).json() == {"matched": False}


async def test_identified_caller_verifies_with_the_date_of_birth_alone(client):
    """Covers: MOCK-16"""
    h = {"X-Identified-Ref": "EVG-482913"}
    assert (await client.post("/mock/healthcare/verify", headers=h, json={"date_of_birth": "1986-04-12"})).json()["verified"] is True
    assert (await client.post("/mock/healthcare/verify", headers=h, json={"date_of_birth": "1986-04-13"})).json()["verified"] is False
    assert (await client.post("/mock/healthcare/verify", json={"date_of_birth": "1986-04-12"})).status_code == 422


async def test_member_profile(client):
    """Covers: MOCK-17"""
    r = await client.get("/mock/healthcare/members/me", headers={"X-Member-Ref": "EVG-482913"})
    body = r.json()
    assert body["first_name"] == "Maria" and body["plan_name"] == "Evergreen Silver PPO" and body["preferred_contact"] == "phone, after 5pm"
    assert body["policies"] and all(p["policy_id"] for p in body["policies"])
    assert [c["claim_id"] for c in body["open_claims"]] == ["C-20977"]  # paid claims are not open; no other member's claims
    assert (await client.get("/mock/healthcare/members/me")).status_code == 401
