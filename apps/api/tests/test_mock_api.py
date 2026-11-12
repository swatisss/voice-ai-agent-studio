"""Mock Northgate Health API: identity, member profile and Digital GP. Covers: MOCK-01, MOCK-02, MOCK-03, MOCK-15, MOCK-16, MOCK-17, MOCK-22, MOCK-31"""
from __future__ import annotations

import pytest

SARAH = {"X-Member-Ref": "NGH-410237"}
LUCY = {"X-Member-Ref": "NGH-917362"}


async def test_verify_normalizes_id_and_dob(client):
    """Covers: MOCK-01"""
    r = await client.post("/mock/healthcare/verify", json={"member_id": "410237", "date_of_birth": "14 March 1984"})
    assert r.json() == {"verified": True, "member_ref": "NGH-410237", "first_name": "Sarah", "plan_name": "Northgate Complete"}
    for member_id in ("NGH-410237", "ngh 410237"):
        r = await client.post("/mock/healthcare/verify", json={"member_id": member_id, "date_of_birth": "1984-03-14"})
        assert r.json()["verified"] is True
    r = await client.post("/mock/healthcare/verify", json={"member_id": "410237", "date_of_birth": "15 March 1984"})
    assert r.json()["verified"] is False


async def test_claim_of_other_member_is_404(client):
    """Covers: MOCK-02"""
    r = await client.get("/mock/healthcare/claims/CL-70640", headers=SARAH)
    assert r.status_code == 404
    r = await client.get("/mock/healthcare/claims/cl70231", headers=SARAH)  # her own claim, id normalised
    assert r.status_code == 200 and r.json()["claim_id"] == "CL-70231"


async def test_policies_require_member_header(client):
    """Covers: MOCK-03"""
    r = await client.get("/mock/insurance/policies")
    assert r.status_code == 401 and r.json()["error"] == "member_not_verified"


async def test_identify_by_registered_number(client):
    """Covers: MOCK-15"""
    expected = {"matched": True, "member_ref": "NGH-410237", "first_name": "Sarah"}
    assert (await client.post("/mock/healthcare/identify", json={"phone": "+447700900141"})).json() == expected
    assert (await client.post("/mock/healthcare/identify", json={"phone": "07700 900141"})).json() == expected
    assert (await client.post("/mock/healthcare/identify", json={"phone": "+447700900199"})).json() == {"matched": False}


async def test_identified_caller_verifies_with_the_date_of_birth_alone(client):
    """Covers: MOCK-16"""
    h = {"X-Identified-Ref": "NGH-410237"}
    assert (await client.post("/mock/healthcare/verify", headers=h, json={"date_of_birth": "1984-03-14"})).json()["verified"] is True
    assert (await client.post("/mock/healthcare/verify", headers=h, json={"date_of_birth": "1984-03-15"})).json()["verified"] is False
    r = await client.post("/mock/healthcare/verify", json={"date_of_birth": "1984-03-14"})
    assert r.status_code == 422 and r.json()["error"] == "member_id_required"


async def test_member_profile(client):
    """Covers: MOCK-17"""
    body = (await client.get("/mock/healthcare/members/me", headers=SARAH)).json()
    assert body["first_name"] == "Sarah" and body["plan_name"] == "Northgate Complete"
    assert body["policies"] == [{"policy_id": "PMI-300101", "product": "Northgate Complete", "status": "active"}]
    assert body["open_claims"] == []  # CL-70231 is paid; no other member's claims
    text = str(body)
    for other in ("PMI-300214", "PMI-300377", "CL-70412", "CL-70588", "CL-70640", "David", "Emma", "Raj"):
        assert other not in text
    assert (await client.get("/mock/healthcare/members/me")).status_code == 401


async def test_gp_booking_for_a_family_member(client):
    """Covers: MOCK-22"""
    slots = (await client.get("/mock/healthcare/gp/slots", headers=SARAH, params={"type": "gp", "format": "video"})).json()["slots"]
    assert slots and all(s["format"] == "video" for s in slots)
    slot_id = slots[0]["slot_id"]
    r = await client.post("/mock/healthcare/gp/appointments", headers=SARAH, json={"slot_id": slot_id, "reason": "Earache", "patient_name": "Isla"})
    assert r.status_code == 200
    booking = r.json()
    assert booking["booking_id"].startswith("GPB-") and "Isla" in booking["patient"]
    after = (await client.get("/mock/healthcare/gp/slots", headers=SARAH, params={"type": "gp", "format": "video"})).json()["slots"]
    assert slot_id not in [s["slot_id"] for s in after]
    r = await client.post("/mock/healthcare/gp/appointments", headers=SARAH, json={"slot_id": slot_id, "reason": "Earache", "patient_name": "Isla"})
    assert r.status_code == 409 and r.json()["error"] == "slot_taken"
    r = await client.post("/mock/healthcare/gp/appointments", headers=SARAH, json={"slot_id": after[0]["slot_id"], "reason": "Cough", "patient_name": "Oliver"})
    assert r.status_code == 409 and r.json()["error"] == "patient_not_covered"
    r = await client.get("/mock/healthcare/gp/slots", headers=LUCY, params={"type": "gp"})
    assert r.status_code == 409 and r.json()["error"] == "not_covered"


async def test_gp_booking_returns_the_full_name_of_the_patient(client):
    """Covers: MOCK-22"""
    slots = (await client.get("/mock/healthcare/gp/slots", headers=SARAH, params={"type": "gp", "format": "video"})).json()["slots"]
    r = await client.post("/mock/healthcare/gp/appointments", headers=SARAH, json={"slot_id": slots[0]["slot_id"], "reason": "Earache", "patient_name": "Isla"})
    assert r.json()["patient"] == "Isla Mitchell"


@pytest.mark.parametrize("spoken", ["14th of March 1984", "14/03/1984", "14 Mar 1984", "March 14 1984", "1984-03-14"])
async def test_uk_dates_parse(client, spoken):
    """Covers: MOCK-31"""
    r = await client.post("/mock/healthcare/verify", json={"member_id": "NGH-410237", "date_of_birth": spoken})
    assert r.json()["verified"] is True


async def test_numeric_dates_are_day_first(client):
    """Covers: MOCK-31"""
    from voiceai.mock.routes import parse_date

    assert parse_date("03/04/1984").isoformat() == "1984-04-03"  # 3 April, never 4 March
    assert parse_date("03/14/1984") is None  # no 14th month: never read as MM/DD/YYYY
    r = await client.post("/mock/healthcare/verify", json={"member_id": "NGH-410237", "date_of_birth": "03/14/1984"})
    assert r.json()["verified"] is False
