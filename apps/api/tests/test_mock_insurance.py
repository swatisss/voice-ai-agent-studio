"""Mock insurance API: policies, payments, contact details, documents, cash plan and outreach. Covers: MOCK-05, MOCK-18, MOCK-19, MOCK-20, MOCK-21, MOCK-23, MOCK-30"""
from __future__ import annotations

from datetime import date, timedelta

from voiceai.mock import data

SARAH = {"X-Member-Ref": "NGH-410237"}
DAVID = {"X-Member-Ref": "NGH-522918"}
EMMA = {"X-Member-Ref": "NGH-638405"}
LUCY = {"X-Member-Ref": "NGH-917362"}


async def test_policies_are_scoped_to_the_member(client):
    """Covers: MOCK-05"""
    rows = (await client.get("/mock/insurance/policies", headers=SARAH)).json()["policies"]
    assert [p["policy_id"] for p in rows] == ["PMI-300101"]
    detail = (await client.get("/mock/insurance/policies/pmi300101", headers=SARAH)).json()
    assert detail["monthly_premium"] == 187.40 and detail["payment_status"] == "up_to_date"
    assert detail["cover"]["excess"] == 100 and detail["cover"]["outpatient_limit"] == "unlimited" and detail["cover"]["underwriting"] == "moratorium"
    assert (await client.get("/mock/insurance/policies/PMI-300452", headers=SARAH)).status_code == 404
    emma = (await client.get("/mock/insurance/policies", headers=EMMA)).json()["policies"]
    assert [p["policy_id"] for p in emma] == ["PMI-300377", "CSH-400204"]  # health first


async def test_missed_payment_retry(client):
    """Covers: MOCK-18"""
    pay = (await client.get("/mock/insurance/policies/PMI-300214/payments", headers=DAVID)).json()
    assert pay["status"] == "missed" and pay["missed_amount"] == 61.2 and pay["reinstate_by"]
    too_late = (date.fromisoformat(pay["reinstate_by"]) + timedelta(days=1)).isoformat()
    r = await client.post("/mock/insurance/policies/PMI-300214/payments/retry", headers=DAVID, json={"collect_on": too_late})
    assert r.status_code == 422
    r = await client.post("/mock/insurance/policies/PMI-300214/payments/retry", headers=DAVID, json={})
    assert r.status_code == 200
    body = r.json()
    assert body["reference"].startswith("RT-") and body["collect_on"] == data.rel(3) and body["amount"] == 61.2
    r = await client.post("/mock/insurance/policies/PMI-300214/payments/retry", headers=DAVID, json={})
    assert r.status_code == 409 and r.json()["error"] == "nothing_missed"


async def test_collection_day_change(client):
    """Covers: MOCK-19"""
    r = await client.post("/mock/insurance/policies/PMI-300377/payments/collection-day", headers=EMMA, json={"day": 15})
    assert r.status_code == 200
    first_of_next = date.fromisoformat(data._first_of_month(1))
    assert r.json()["collection_day"] == 15 and r.json()["next_collection_date"] == first_of_next.replace(day=15).isoformat()
    r = await client.post("/mock/insurance/policies/PMI-300377/payments/collection-day", headers=EMMA, json={"day": 31})
    assert r.status_code == 422
    r = await client.post("/mock/insurance/policies/PMI-300214/payments/collection-day", headers=DAVID, json={"day": 15})
    assert r.status_code == 409 and r.json()["error"] == "payment_missed"


async def test_contact_change_and_secure_link(client):
    """Covers: MOCK-20"""
    r = await client.post("/mock/insurance/members/me/contact", headers=SARAH, json={"email": "sarah.new@example.co.uk"})
    assert r.status_code == 200
    body = r.json()
    assert body["reference"].startswith("CH-") and body["changed"] == ["email"]
    assert body["confirmation_sent_to"] == "s***@example.co.uk"
    r = await client.post("/mock/insurance/members/me/contact", headers=SARAH, json={"address": "14 Larkfield Road, Leeds"})
    assert r.status_code == 422
    request = {"purpose": "change_bank_details", "channel": "sms"}
    r = await client.post("/mock/insurance/secure-links", headers=SARAH, json=request)
    assert r.status_code == 200
    link = r.json()
    assert link["link_id"].startswith("SL-") and link["channel"] == "sms" and link["expires_in_hours"] == 24
    assert link["sent_to"] == "mobile ending 141"
    text = (str(request) + r.text).lower()
    assert "4821" not in text and "sort code" not in text and "account number" not in text and "account ending" not in text


async def test_documents_by_policy_type(client):
    """Covers: MOCK-21"""
    health = (await client.get("/mock/insurance/documents", headers=EMMA, params={"policy_id": "PMI-300377"})).json()["documents"]
    cash = (await client.get("/mock/insurance/documents", headers=EMMA, params={"policy_id": "CSH-400204"})).json()["documents"]
    health_types, cash_types = {d["document_type"] for d in health}, {d["document_type"] for d in cash}
    assert "membership_certificate" in health_types and "table_of_benefits" not in health_types
    assert "table_of_benefits" in cash_types and "membership_certificate" not in cash_types
    r = await client.post("/mock/insurance/documents/request", headers=EMMA,
                          json={"policy_id": "PMI-300377", "document_type": "membership certificate", "delivery": "email"})
    assert r.json()["status"] == "queued" and r.json()["sent_to"] == "e***@example.co.uk"
    r = await client.post("/mock/insurance/documents/request", headers=EMMA,
                          json={"policy_id": "PMI-300377", "document_type": "membership_certificate", "delivery": "post"})
    assert r.json()["status"] == "scheduled"
    r = await client.post("/mock/insurance/documents/request", headers=EMMA,
                          json={"policy_id": "PMI-300377", "document_type": "table_of_benefits", "delivery": "email"})
    assert r.status_code == 409 and r.json()["error"] == "document_not_available" and "membership_certificate" in r.json()["available"]


async def test_cash_plan_benefits_and_claims(client):
    """Covers: MOCK-23"""
    body = (await client.get("/mock/insurance/policies/CSH-400118/cash-benefits", headers=LUCY)).json()
    assert body["level"] == "Level 3"
    benefits = {b["benefit"]: b for b in body["benefits"]}
    assert benefits["optical"]["yearly_limit"] == 200
    assert benefits["dental"]["used"] == 145 and benefits["dental"]["remaining"] == 255
    claim = (await client.get("/mock/insurance/cash-plan/claims/cc81377", headers=LUCY)).json()
    assert claim["claim_id"] == "CC-81377" and claim["status"] == "processing" and claim["expected_decision_date"]
    r = await client.get("/mock/insurance/policies/PMI-300101/cash-benefits", headers=SARAH)
    assert r.status_code == 409 and r.json()["error"] == "not_a_cash_plan"


async def test_renewal_outreach_targets(client):
    """Covers: MOCK-30"""
    targets = (await client.get("/mock/insurance/outreach/renewals")).json()["targets"]
    assert len(targets) == 1
    t = targets[0]
    assert t["member_ref"] == "NGH-410237" and t["first_name"] == "Sarah"
    ctx = t["context"]
    assert ctx["member_id"] == "410237" and ctx["policy_id"] == "PMI-300101" and ctx["days_to_renewal"] == 45 and ctx["purpose"]
