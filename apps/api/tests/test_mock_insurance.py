"""Mock insurance and internal API. Covers: MOCK-05, MOCK-06, MOCK-07, MOCK-08, MOCK-09, MOCK-10, MOCK-11, MOCK-12"""
from __future__ import annotations

from datetime import timedelta

from voiceai.modules.businessmock import data

MARIA = {"X-Member-Ref": "EVG-482913"}
JAMES = {"X-Member-Ref": "EVG-337120"}
AISHA = {"X-Member-Ref": "EVG-725031"}
DANIEL = {"X-Member-Ref": "EVG-801456"}
PRIYA = {"X-Member-Ref": "EVG-559804"}


def _trip(start_in_days: int = 20, length: int = 10) -> dict[str, str]:
    start = data.today() + timedelta(days=start_in_days)
    return {"travel_start": start.isoformat(), "travel_end": (start + timedelta(days=length - 1)).isoformat()}


async def test_policies_are_scoped_to_the_member(client):
    """Covers: MOCK-05"""
    rows = (await client.get("/mock/insurance/policies", headers=MARIA)).json()["policies"]
    assert [p["policy_id"] for p in rows] == ["HP-100231"]
    detail = (await client.get("/mock/insurance/policies/hp100231", headers=MARIA)).json()
    assert detail["annual_premium"] == 2548.80 and detail["payment_status"] == "up_to_date" and detail["renewal_date"] == data.rel(25)
    assert (await client.get("/mock/insurance/policies/MP-200415", headers=MARIA)).status_code == 404
    assert (await client.get("/mock/insurance/policies")).status_code == 401
    assert (await client.get("/mock/insurance/policies/HP-100231")).status_code == 401


async def test_coverage_remaining_waiting_period_and_not_applicable(client):
    """Covers: MOCK-06"""
    r = (await client.get("/mock/insurance/policies/HP-100231/coverage", params={"benefit": "dental"}, headers=MARIA)).json()
    assert r["covered"] and r["annual_limit"] == 800 and r["used"] == 320 and r["remaining"] == 480
    assert r["waiting_period_days"] == 90 and r["copay_percent"] == 20
    alias = (await client.get("/mock/insurance/policies/HP-100231/coverage", params={"benefit": "Dentist"}, headers=MARIA)).json()
    assert alias["benefit"] == "dental"
    bronze = (await client.get("/mock/insurance/policies/HP-100877/coverage", params={"benefit": "dental"}, headers=AISHA)).json()
    assert bronze["covered"] is False and bronze["remaining"] is None
    assert (await client.get("/mock/insurance/policies/MP-200415/coverage", params={"benefit": "dental"}, headers=JAMES)).json()["error"] == "not_applicable"
    assert (await client.get("/mock/insurance/policies/HP-100231/coverage", params={"benefit": "teleportation"}, headers=MARIA)).status_code == 422


async def test_documents_and_delivery(client):
    """Covers: MOCK-07"""
    health = (await client.get("/mock/insurance/documents", params={"policy_id": "HP-100412"}, headers=JAMES)).json()["documents"]
    motor = (await client.get("/mock/insurance/documents", params={"policy_id": "MP-200415"}, headers=JAMES)).json()["documents"]
    assert "green_card" not in {d["document_type"] for d in health} and "green_card" in {d["document_type"] for d in motor}
    body = {"policy_id": "HP-100231", "document_type": "policy_schedule"}
    email = (await client.post("/mock/insurance/documents/request", json={**body, "delivery": "email"}, headers=MARIA)).json()
    assert email["sent_to"] == "m***@example.com" and email["eta"] == "within 15 minutes" and email["status"] == "queued"
    post = (await client.post("/mock/insurance/documents/request", json={**body, "delivery": "post"}, headers=MARIA)).json()
    assert post["eta"] == "5-7 business days"
    link = (await client.post("/mock/insurance/documents/request", json={**body, "delivery": "download"}, headers=MARIA)).json()
    assert link["download_url"].startswith("https://portal.evergreen.example/docs/")
    assert [d["delivery"] for d in data.DOCUMENT_REQUESTS] == ["email", "post", "download"]


async def test_green_card_rules(client):
    """Covers: MOCK-08"""
    url = "/mock/insurance/documents/request"
    base = {"policy_id": "MP-200415", "document_type": "green_card", "delivery": "email"}
    ok = (await client.post(url, json={**base, "countries": ["Spain"], **_trip()}, headers=JAMES)).json()
    assert ok["status"] == "queued" and ok["valid_from"] == _trip()["travel_start"] and ok["valid_to"] == _trip()["travel_end"] and ok["countries"] == ["Spain"]
    usa = await client.post(url, json={**base, "countries": ["the USA"], **_trip()}, headers=JAMES)
    assert usa.status_code == 409 and usa.json()["error"] == "country_not_covered" and usa.json()["unsupported_countries"] == ["USA"]
    long_trip = await client.post(url, json={**base, "countries": "Spain and France", **_trip(length=120)}, headers=JAMES)
    assert long_trip.status_code == 422 and long_trip.json()["error"] == "invalid_travel_dates"
    health = await client.post(url, json={**base, "policy_id": "HP-100412", "countries": ["Spain"], **_trip()}, headers=JAMES)
    assert health.status_code == 409 and health.json()["error"] == "not_a_motor_policy"
    by_post = await client.post(url, json={**base, "delivery": "post", "countries": ["Spain"], **_trip()}, headers=JAMES)
    assert by_post.status_code == 409 and by_post.json()["error"] == "delivery_not_available"
    missing = await client.post(url, json=base, headers=JAMES)
    assert missing.status_code == 422 and missing.json()["error"] == "missing_travel_details"


async def test_renewal_quote_and_decision(client):
    """Covers: MOCK-09"""
    quote = (await client.get("/mock/insurance/policies/MP-200415/renewal-quote", headers=JAMES)).json()
    assert quote["renewal_premium"] == 738.70 and quote["change_percent"] == 8.0 and quote["days_to_renewal"] == 13
    assert quote["reasons"] and len(quote["options"]) == 2 and quote["renewal_status"] == "pending"
    far = await client.get("/mock/insurance/policies/HP-100655/renewal-quote", headers=PRIYA)
    assert far.status_code == 409 and far.json()["error"] == "not_in_renewal_window"
    url = "/mock/insurance/policies/MP-200415/renewal-decision"
    no_time = await client.post(url, json={"decision": "callback"}, headers=JAMES)
    assert no_time.status_code == 422 and no_time.json()["error"] == "callback_time_required"
    bad = await client.post(url, json={"decision": "maybe"}, headers=JAMES)
    assert bad.status_code == 422
    accepted = (await client.post(url, json={"decision": "accept", "option": "Renew as is"}, headers=JAMES)).json()
    assert accepted["renewal_status"] == "accepted" and accepted["reference"].startswith("RN-")
    assert (await client.get("/mock/insurance/policies/MP-200415/renewal-quote", headers=JAMES)).json()["renewal_status"] == "accepted"


async def test_onboarding_checklist(client):
    """Covers: MOCK-10"""
    start = (await client.get("/mock/insurance/onboarding", headers=AISHA)).json()
    assert start["remaining"] == 5 and next(s for s in start["steps"] if s["step_id"] == "confirm_contact_details")["status"] == "done"
    done = (await client.post("/mock/insurance/onboarding/steps/communication_preferences", json={"value": "email"}, headers=AISHA)).json()
    assert done["remaining"] == 4
    bad = await client.post("/mock/insurance/onboarding/steps/communication_preferences", json={"value": "carrier pigeon"}, headers=AISHA)
    assert bad.status_code == 422 and bad.json()["error"] == "invalid_preference"
    unknown = await client.post("/mock/insurance/onboarding/steps/skydiving", json={}, headers=AISHA)
    assert unknown.status_code == 404 and unknown.json()["error"] == "step_not_found"
    assert (await client.get("/mock/insurance/onboarding")).status_code == 401


async def test_outreach_lists(client):
    """Covers: MOCK-11"""
    renewals = (await client.get("/mock/insurance/outreach/renewals")).json()["targets"]
    assert [t["first_name"] for t in renewals] == ["James", "Maria", "Robert"]
    james = renewals[0]
    assert james["member_ref"] == "EVG-337120" and james["context"]["policy_id"] == "MP-200415" and james["context"]["days_to_renewal"] == 13
    assert james["context"]["premium_change_percent"] == 8.0 and james["context"]["member_id"] == "337120"
    await client.post("/mock/insurance/policies/MP-200415/renewal-decision", json={"decision": "decline"}, headers=JAMES)
    assert [t["first_name"] for t in (await client.get("/mock/insurance/outreach/renewals")).json()["targets"]] == ["Maria", "Robert"]

    onboarding = (await client.get("/mock/insurance/outreach/onboarding")).json()["targets"]
    assert [(t["first_name"], t["context"]["steps_remaining"]) for t in onboarding] == [("Aisha", 5), ("Daniel", 3)]
    for step in ("communication_preferences", "choose_primary_provider", "review_waiting_periods"):
        await client.post(f"/mock/insurance/onboarding/steps/{step}", json={"value": "sms"}, headers=DANIEL)
    assert [t["first_name"] for t in (await client.get("/mock/insurance/outreach/onboarding")).json()["targets"]] == ["Aisha"]


async def test_internal_reference_endpoints(client):
    """Covers: MOCK-12"""
    r = (await client.get("/mock/internal/authorization-limits", params={"role": "claims_handler", "claim_type": "inpatient"})).json()
    assert r["limit"] == 5000
    assert (await client.get("/mock/internal/authorization-limits", params={"role": "claims_handler"})).json()["limits"]["dental"] == 1000
    assert (await client.get("/mock/internal/authorization-limits", params={"role": "intern"})).status_code == 404
    contact = (await client.get("/mock/internal/contacts", params={"topic": "Fraud"})).json()
    assert contact["team"] == "Special Investigations Unit" and contact["extension"] == "4410"
    unknown = await client.get("/mock/internal/contacts", params={"topic": "parking"})
    assert unknown.status_code == 404 and "fraud" in unknown.json()["topics"]
