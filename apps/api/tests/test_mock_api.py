"""Mock healthcare API. Covers: MOCK-01, MOCK-02, MOCK-03, MOCK-04"""
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
