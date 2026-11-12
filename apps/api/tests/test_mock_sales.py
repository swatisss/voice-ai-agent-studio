"""Mock sales API: quotes, underwriting and applications. Covers: MOCK-27, MOCK-28, MOCK-29"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from voiceai.mock import data

COUPLE = [{"name": "Anna Hughes", "date_of_birth": "1990-05-05"}, {"name": "Ben Hughes", "date_of_birth": "1992-02-02", "relationship": "partner"}]
HOLDER = {"first_name": "Anna", "last_name": "Hughes", "email": "anna.hughes@example.co.uk", "mobile": "07700 900150",
          "address": "9 Cotham Road, Bristol BS6 6JY"}


async def _quote(client, people=COUPLE, postcode="BS6 6JY"):  # noqa: ANN001, ANN202
    r = await client.post("/mock/sales/quotes", json={"people": people, "postcode": postcode})
    assert r.status_code == 200, r.text
    return r.json()


async def _priced(client, **selection):  # noqa: ANN001, ANN003, ANN202
    q = await _quote(client)
    r = await client.post(f"/mock/sales/quotes/{q['quote_id']}/price", json=selection or {"package": "balanced"})
    assert r.status_code == 200, r.text
    return q["quote_id"], r.json()


async def test_quote_and_price(client):
    """Covers: MOCK-27"""
    q = await _quote(client)
    assert [p["package"] for p in q["packages"]] == ["essentials", "balanced", "complete"]
    totals = [p["monthly_total"] for p in q["packages"]]
    assert totals == sorted(totals) and len(set(totals)) == 3  # cheapest first
    assert q["valid_until"] == data.rel(14)
    r = await client.post(f"/mock/sales/quotes/{q['quote_id']}/price", json={"package": "balanced", "add_ons": ["dental_optical"]})
    priced = r.json()
    assert priced["multi_person_discount_percent"] == 5 and priced["add_ons_monthly"] == 23.0

    async def single(smoker: bool, postcode: str = "BS6 6JY") -> float:
        quote = await _quote(client, [{"date_of_birth": "1990-05-05", "smoker": smoker}], postcode)
        return quote["packages"][1]["monthly_total"]

    plain, smoker = await single(False), await single(True)
    assert smoker == pytest.approx(plain * 1.10, abs=0.02)
    assert await single(False, "SW11 1AA") > plain  # London costs more than Bristol
    start = data.today() + timedelta(days=1)  # the default start date
    old = date(start.year - 80, start.month, min(start.day, 28)) - timedelta(days=1)  # 80 on the start date
    r = await client.post("/mock/sales/quotes", json={"people": [{"date_of_birth": old.isoformat()}], "postcode": "BS6 6JY"})
    assert r.status_code == 422 and r.json()["error"] == "age_not_eligible"


async def test_central_london_postcode_costs_more_than_bristol(client):
    """Covers: MOCK-27"""
    london = await _quote(client, [{"date_of_birth": "1990-05-05"}], "SW1A 1AA")
    bristol = await _quote(client, [{"date_of_birth": "1990-05-05"}], "BS6 6JY")
    assert london["region"] == "London" and london["packages"][1]["monthly_total"] > bristol["packages"][1]["monthly_total"]


async def test_outpatient_limit_on_essentials_is_rejected(client):
    """Covers: MOCK-27"""
    q = await _quote(client)
    r = await client.post(f"/mock/sales/quotes/{q['quote_id']}/price", json={"product": "essentials", "outpatient_limit": "1000", "excess": 250,
                                                                             "hospital_list": "essential"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_option"


async def test_underwriting(client):
    """Covers: MOCK-28"""
    q = await _quote(client)
    r = await client.post(f"/mock/sales/quotes/{q['quote_id']}/underwriting", json={"method": "moratorium"})
    assert r.status_code == 409 and r.json()["error"] == "no_cover_selected"

    qid, _ = await _priced(client)
    mori = (await client.post(f"/mock/sales/quotes/{qid}/underwriting", json={"method": "moratorium"})).json()
    fmu = (await client.post(f"/mock/sales/quotes/{qid}/underwriting", json={"method": "full_medical", "answers": [
        {"person": "Anna", "conditions": ["asthma"]}, {"person": "Ben", "conditions": []}]})).json()
    assert fmu["decision"] == "accept_with_exclusions"
    assert fmu["people"][0]["exclusions"] == ["asthma and related conditions"] and fmu["people"][1]["exclusions"] == []
    assert fmu["monthly_total"] == pytest.approx(mori["monthly_total"] * 0.95, abs=0.02)

    heart = (await client.post(f"/mock/sales/quotes/{qid}/underwriting", json={"method": "full_medical", "answers": [
        {"person": "Anna", "conditions": ["heart murmur"]}, {"person": "Ben", "conditions": []}]})).json()
    assert heart["decision"] == "refer_to_underwriter"
    r = await client.post(f"/mock/sales/quotes/{qid}/underwriting", json={"method": "full_medical", "answers": [{"person": "Anna", "conditions": []}]})
    assert r.status_code == 422 and r.json()["error"] == "answers_required" and r.json()["missing"] == ["Ben Hughes"]
    r = await client.post(f"/mock/sales/quotes/{qid}/underwriting", json={"method": "switch", "previous_insurer": "Other Insurer",
                                                                          "continuous_cover_months": 6})
    assert r.status_code == 409 and r.json()["error"] == "switch_not_eligible"


async def test_application(client):
    """Covers: MOCK-29"""
    qid, _ = await _priced(client)
    uw = (await client.post(f"/mock/sales/quotes/{qid}/underwriting", json={"method": "moratorium"})).json()
    assert uw["decision"] == "accept"
    body = {"quote_id": qid, "underwriting_id": uw["underwriting_id"], "policyholder": HOLDER, "documents_by": "email", "payment_link_by": "sms",
            "key_facts_confirmed": False, "declaration_confirmed": True}
    r = await client.post("/mock/sales/applications", json=body)
    assert r.status_code == 422 and r.json()["error"] == "confirmation_required"
    r = await client.post("/mock/sales/applications", json={**body, "key_facts_confirmed": True})
    assert r.status_code == 200, r.text
    app = r.json()
    assert app["policy_id"].startswith("PMI-31") and app["membership_number"].startswith("NGH-96")
    assert date.fromisoformat(app["cooling_off_ends"]) == date.fromisoformat(app["start_date"]) + timedelta(days=21)
    assert app["documents_sent_to"] == "a***@example.co.uk" and app["direct_debit_link_sent_to"] == "mobile ending 150"
    v = (await client.post("/mock/healthcare/verify", json={"member_id": app["membership_number"], "date_of_birth": "1990-05-05"})).json()
    assert v["verified"] is True and v["member_ref"] == app["membership_number"]
    policies = (await client.get("/mock/insurance/policies", headers={"X-Member-Ref": v["member_ref"]})).json()["policies"]
    assert [p["policy_id"] for p in policies] == [app["policy_id"]]
    r = await client.post("/mock/sales/applications", json={**body, "key_facts_confirmed": True})
    assert r.status_code == 409 and r.json()["error"] == "already_applied"

    qid2, _ = await _priced(client)
    referred = (await client.post(f"/mock/sales/quotes/{qid2}/underwriting", json={"method": "full_medical", "answers": [
        {"person": "Anna", "conditions": ["cancer"]}, {"person": "Ben", "conditions": []}]})).json()
    assert referred["decision"] == "refer_to_underwriter"
    r = await client.post("/mock/sales/applications", json={**body, "quote_id": qid2, "underwriting_id": referred["underwriting_id"],
                                                             "key_facts_confirmed": True})
    assert r.status_code == 409 and r.json()["error"] == "referred_to_underwriter"
