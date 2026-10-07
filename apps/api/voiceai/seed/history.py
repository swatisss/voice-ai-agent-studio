"""Deterministic synthetic call history for the Customer Care agent.

Spec: /demo-data/call-history.md
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from voiceai.mock import data as mock

GREETING = "Thanks for calling Evergreen Health member services, this is Ava. I'm a virtual assistant, and this call may be recorded for quality. How can I help you today?"
HANDOFF = "I'm connecting you with a specialist who will have all the details, so you won't need to repeat yourself."
ASSIGNEES = ["Dana (Customer Care)", "Luis (Customer Care)", "Morgan (Appeals)"]

MIX = [  # (intent, count)
    ("policy_status", 14), ("claim_status", 26), ("document_request", 16), ("coverage_question", 20), ("find_provider", 6),
    ("add_dependent_newborn", 14), ("prior_auth_status", 9), ("claim_appeal", 8), ("provider_billing_dispute", 3),
    ("speak_to_person", 4), ("abandoned", 3),
]
WEEKLY = [27, 30, 32, 34]
NEWBORN_WEEKLY = [3, 3, 4, 4]

ESCALATED = {
    "add_dependent_newborn": ("knowledge_gap", "missing_knowledge", "newborn"),
    "prior_auth_status": ("capability_gap", "missing_skill", "prior_auth"),
    "claim_appeal": ("policy_required", "policy_required", "appeals"),
    "provider_billing_dispute": ("policy_required", "policy_required", "billing_dispute"),
    "speak_to_person": ("caller_requested", "caller_requested", "caller_requested"),
}

CLUSTERS = {
    "newborn": ("Adding a newborn to coverage", "Callers want to know how and when to add a new baby to their plan; no approved article exists."),
    "prior_auth": ("Prior authorization status", "Callers want the status of a prior authorization; the agent has no lookup tool."),
    "appeals": ("Claim denial appeals", "Callers want to appeal denied claims, which policy routes to specialists."),
    "billing_dispute": ("Provider billing disputes", "Callers dispute provider bills; requires investigation by a specialist."),
    "caller_requested": ("Asked for a person", "Callers asked for a person at the start of the call."),
}

GAPS = {
    "newborn": ["How to add a newborn to an existing plan", "Deadline and steps to enroll a new baby on the policy", "Adding a newborn dependent after birth"],
    "prior_auth": ["Checking the status of a prior authorization", "Whether a pending prior authorization has been decided"],
    "appeals": ["Filing an appeal for a denied claim"],
    "billing_dispute": ["Disputing a duplicate or incorrect provider bill"],
    "caller_requested": ["Caller asked for a person without a specific unmet need"],
}

NOTES = {
    "newborn": [
        "Explained newborns can be added within 60 days of birth as a qualifying life event; coverage is retroactive to the date of birth. Walked her through member portal > Coverage > Life events > Add a dependent.",
        "Added baby by phone. Needs birth certificate or hospital birth record uploaded within 30 days; SSN can be added later. Premium may change at next bill.",
        "Told caller the 60-day window from birth; if missed, must wait for open enrollment. Baby's ID card mails in 7-10 business days, digital card in the app within 2 business days.",
        "Caller asked if hospital stay is covered for baby - yes once added within 60 days, retroactive to birth. Sent portal instructions (Coverage > Life events).",
        "Submitted add-dependent request on caller's behalf; reminded her to upload the hospital birth record within 30 days to avoid termination of the dependent.",
    ],
    "prior_auth": [
        "Looked up PA in UM system: pending clinical review, decision expected within 2 business days; told caller provider will be notified.",
        "PA approved; gave approval and valid-through dates. Caller can schedule the procedure.",
        "PA denied for insufficient documentation; explained provider can resubmit with additional records.",
    ],
    "appeals": [
        "Filed standard appeal for denied claim; explained 30-day decision timeline and mailed confirmation letter.",
        "Started expedited appeal (urgent); decision within 72 hours.",
    ],
    "billing_dispute": ["Opened billing review ticket with provider relations; caller will hear back in 10 business days."],
    "caller_requested": ["Answered general questions about the plan; no further action needed."],
}

GOALS = {
    "newborn": "You recently had a baby and want to know how to add the baby to your health plan.",
    "appeals": "Your claim was denied and you want to appeal it.",
    "billing_dispute": "You think your doctor billed you twice for the same visit and want it fixed.",
    "caller_requested": "You want to speak with a person.",
}

GREEN_CARD_CALLS = {1, 3, 6, 8, 11, 14}  # which of the 16 document_request calls ask for a Green Card
GREEN_CARD_TRIPS = ["Spain", "France", "Italy", "Germany", "Portugal", "Greece"]
DOCUMENTS = [("policy_schedule", "policy schedule"), ("membership_card", "membership card"), ("premium_invoice", "premium invoice"),
             ("policy_wording", "policy wording"), ("tax_certificate", "annual premium statement")]
COVERAGE_BENEFITS = ["dental", "optical", "outpatient", "maternity", "mental_health", "dental", "outpatient", "optical"]

AUTH_OWNERS = {"PA-77930": "EVG-725031", "PA-77812": "EVG-559804", "PA-78001": "EVG-610277"}


@dataclass
class SeedCall:
    started_at: datetime
    intent: str
    outcome: str
    member_ref: str | None
    events: list[tuple[str, str | None, dict[str, Any]]] = field(default_factory=list)
    tools_used: list[dict[str, Any]] = field(default_factory=list)
    escalation: dict[str, Any] | None = None
    analysis: dict[str, Any] = field(default_factory=dict)
    cluster_key: str | None = None
    cost: float = 0.0
    latency_ms: int = 900


def _spoken_dob(dob: str) -> str:
    d = date.fromisoformat(dob)
    return f"{d:%B} {d.day}, {d.year}"


def _verify(c: SeedCall, member_ref: str) -> None:
    m = mock.MEMBERS[member_ref]
    c.events += [
        ("assistant", "I can help with that. Can I have your member ID and date of birth?", {}),
        ("user", f"Sure, it's {member_ref.split('-')[1]}, {_spoken_dob(m['dob'])}.", {}),
        ("tool_call", None, {"name": "verify_member", "args": {"member_id": member_ref.split('-')[1], "date_of_birth": m["dob"]}}),
        ("tool_result", None, {"name": "verify_member", "ok": True, "result": {"verified": True, "member_ref": member_ref, "first_name": m["first_name"]}}),
    ]
    c.tools_used.append({"name": "verify_member", "ok": True, "summary": "verify_member: verified=True"})


def _tool(c: SeedCall, name: str, args: dict[str, Any], result: dict[str, Any], summary: str) -> None:
    c.events += [("tool_call", None, {"name": name, "args": args}), ("tool_result", None, {"name": name, "ok": True, "result": result})]
    c.tools_used.append({"name": name, "ok": True, "summary": summary})


def _build(intent: str, when: datetime, rng: random.Random, counters: dict[str, int]) -> SeedCall:
    members = sorted(mock.MEMBERS)
    member_ref = rng.choice(members)
    m = mock.MEMBERS[member_ref]
    plan = mock.PLANS[m["plan"]]
    c = SeedCall(started_at=when, intent=intent, outcome="resolved", member_ref=member_ref)
    c.events.append(("assistant", GREETING, {"greeting": True}))
    idx = counters.setdefault(intent, 0)
    counters[intent] += 1

    if intent == "policy_status":
        pid, pol = next((i, p) for i, p in mock.POLICIES.items() if p["member"] == member_ref and p["type"] == "health")
        c.events.append(("user", rng.choice(["Hi, is my health policy still active, and when does it renew?", "Can you check my policy status and my next payment date?"]), {}))
        _verify(c, member_ref)
        _tool(c, "get_member_policies", {}, {"policies": [{"policy_id": pid, "status": pol["status"], "renewal_date": pol["renewal_date"]}]}, "get_member_policies: 1 policies")
        _tool(c, "get_policy_details", {"policy_id": pid}, {"policy_id": pid, "status": pol["status"], "payment_status": pol["payment_status"]},
              f"get_policy_details: policy_id={pid}, status={pol['status']}")
        ans = f"Your {pol['product']} is {pol['status']} and renews on {date.fromisoformat(pol['renewal_date']):%B} {date.fromisoformat(pol['renewal_date']).day}."
        if pol["payment_status"] == "overdue":
            ans += " A payment is overdue, but you are still inside the grace period."
        c.events += [("assistant", ans, {}), ("user", "Great, thanks.", {}), ("assistant", "Thank you for calling. Take care!", {})]
        goal, resolution = "You want to know if your health policy is active and when it renews.", ans
    elif intent == "claim_status":
        owners = {cl["member"] for cl in mock.CLAIMS.values()}
        if member_ref not in owners:
            member_ref = "EVG-482913"
            c.member_ref = member_ref
        cid = rng.choice([cid for cid, cl in mock.CLAIMS.items() if cl["member"] == member_ref])
        cl = mock.CLAIMS[cid]
        c.events.append(("user", "Hi, I'm calling to check on a claim.", {}))
        _verify(c, member_ref)
        c.events += [("assistant", f"Thanks, {mock.MEMBERS[member_ref]['first_name']}. What's the claim number?", {}), ("user", f"It's {cid}.", {})]
        _tool(c, "get_claim_status", {"claim_id": cid}, {"claim_id": cid, "status": cl["status"]}, f"get_claim_status: claim_id={cid}, status={cl['status']}")
        if cl["status"] == "paid":
            paid = date.fromisoformat(cl["paid_date"])
            ans = f"That claim for {cl['service'].lower()} was paid on {paid:%B} {paid.day}. The plan paid ${cl['plan_paid']:,.0f} and your share is ${cl['member_responsibility']:,.0f}."
        elif cl["status"] == "denied":
            ans = f"That claim was denied: {cl['denial_reason'].lower()}. An appeals specialist can help you appeal."
        else:
            ans = f"That claim is {cl['status']}." + (" A decision is expected within a few days." if "expected_decision_date_offset" in cl else "")
        c.events += [("assistant", ans, {}), ("user", "Great, that's all. Thanks!", {}), ("assistant", "Thank you for calling. Take care!", {})]
        goal, resolution = f"You want to know the status of claim {cid}.", ans
    elif intent == "document_request" and idx in GREEN_CARD_CALLS:
        member_ref = "EVG-337120"
        c.member_ref = member_ref
        country = GREEN_CARD_TRIPS[idx % len(GREEN_CARD_TRIPS)]
        c.events.append(("user", f"I'm driving to {country} next month and need a Green Card.", {}))
        _verify(c, member_ref)
        trip = when.date() + timedelta(days=30)
        end_trip = trip + timedelta(days=10)
        args = {"policy_id": "MP-200415", "document_type": "green_card", "delivery": "email", "countries": [country],
                "travel_start": trip.isoformat(), "travel_end": end_trip.isoformat()}
        _tool(c, "request_document", args, {"request_id": f"DOC-{900 + idx}", "status": "queued", "eta": "within 15 minutes"}, f"request_document: request_id=DOC-{900 + idx}, status=queued")
        ans = f"Done. Your Green Card for {country} is valid from {trip:%B} {trip.day} to {end_trip:%B} {end_trip.day} and will be emailed within 15 minutes."
        c.events += [("assistant", ans, {}), ("user", "Perfect, thank you.", {}), ("assistant", "Thank you for calling. Take care!", {})]
        goal, resolution = f"You are driving to {country} and want a Green Card for your car policy.", ans
    elif intent == "document_request":
        pid, pol = next((i, p) for i, p in mock.POLICIES.items() if p["member"] == member_ref and p["type"] == "health")
        dtype, title = DOCUMENTS[idx % len(DOCUMENTS)]
        c.events.append(("user", f"Can you email me my {title}?", {}))
        _verify(c, member_ref)
        _tool(c, "request_document", {"policy_id": pid, "document_type": dtype, "delivery": "email"}, {"request_id": f"DOC-{800 + idx}", "status": "queued", "eta": "within 15 minutes"},
              f"request_document: request_id=DOC-{800 + idx}, status=queued")
        ans = f"I've emailed your {title} to the address on file. It should arrive within 15 minutes."
        c.events += [("assistant", ans, {}), ("user", "Thanks, that's all.", {}), ("assistant", "Thank you for calling. Take care!", {})]
        goal, resolution = f"You want your {title} emailed to you.", ans
    elif intent == "coverage_question" and idx % 4 == 3:
        visit = rng.choice(["specialist", "urgent_care", "primary_care"])
        c.events.append(("user", f"What's my copay for {visit.replace('_', ' ')}, and how much of my deductible is left?", {}))
        _verify(c, member_ref)
        remaining = max(plan["deductible"] - m["ded_met"], 0)
        _tool(c, "get_benefits", {}, {"deductible": {"individual": plan["deductible"], "met": m["ded_met"], "remaining": remaining}, "copays": plan["copays"]},
              f"get_benefits: remaining={remaining}")
        ans = f"Your {visit.replace('_', ' ')} copay is ${plan['copays'][visit]}, and ${remaining:,} of your ${plan['deductible']:,} deductible remains."
        c.events += [("assistant", ans, {}), ("user", "Got it, thanks.", {}), ("assistant", "Thank you for calling. Take care!", {})]
        goal, resolution = f"You want to know your {visit.replace('_', ' ')} copay and your remaining deductible.", ans
    elif intent == "coverage_question":
        pid, pol = next((i, p) for i, p in mock.POLICIES.items() if p["member"] == member_ref and p["type"] == "health")
        benefit = COVERAGE_BENEFITS[idx % len(COVERAGE_BENEFITS)]
        covered, limit, copay, wait, preauth, _notes = mock.BENEFITS[pol["product"]][benefit]
        label = benefit.replace("_", " ")
        c.events.append(("user", f"How much of my {label} cover do I have left, and is there a waiting period?", {}))
        _verify(c, member_ref)
        used = mock.USAGE.get(member_ref, {}).get(benefit, 0) if covered else 0
        remaining = (max(limit - used, 0) if limit is not None else None) if covered else None
        _tool(c, "get_coverage_detail", {"policy_id": pid, "benefit": benefit}, {"policy_id": pid, "benefit": benefit, "covered": covered, "remaining": remaining},
              f"get_coverage_detail: covered={covered}, remaining={remaining}")
        if not covered:
            ans = f"{label.capitalize()} is not covered on your {pol['product']}."
        else:
            ans = (f"You have ${remaining:,} of your ${limit:,} {label} limit left." if limit is not None else f"Your {label} cover has no annual limit.")
            ans += f" There is a {wait}-day waiting period." if wait else " There is no waiting period."
        c.events += [("assistant", ans, {}), ("user", "Thanks, that's clear.", {}), ("assistant", "Thank you for calling. Take care!", {})]
        goal, resolution = f"You want to know how much {label} cover is left and whether there is a waiting period.", ans
    elif intent == "find_provider":
        spec, zip_code = rng.choice([("dermatology", "94110"), ("pediatrics", "94110"), ("primary care", "94124"), ("orthopedics", "94115"), ("dentistry", "94110")])
        prov = next(p for p in mock.PROVIDERS if spec in p["specialty"].lower())
        c.member_ref = None
        c.events.append(("user", f"I need an in-network {spec} doctor near {zip_code}.", {}))
        _tool(c, "find_providers", {"specialty": spec, "zip": zip_code}, {"providers": [prov]}, "find_providers: 1 providers")
        ans = f"{prov['name']} at {prov['practice']} is in network and {'is' if prov['accepting_new_patients'] else 'is not'} accepting new patients."
        c.events += [("assistant", ans, {}), ("user", "Thanks, that helps.", {}), ("assistant", "Thank you for calling. Take care!", {})]
        goal, resolution = f"You want an in-network {spec} doctor near zip code {zip_code}.", ans
    elif intent == "abandoned":
        c.events.append(("user", rng.choice(["Hi, um, I had a question about my bill...", "Hello? Can you hear me?", "I wanted to ask about"]), {}))
        c.outcome, c.member_ref = "abandoned", None
        c.analysis = {"outcome": "abandoned", "intent": "unknown", "root_cause": "other", "gap_summary": "", "caller_goal": "",
                      "resolution_summary": "", "sentiment_start": "neutral", "sentiment_end": "neutral"}
        return c
    else:
        category, root, key = ESCALATED[intent]
        c.outcome, c.cluster_key = "escalated", key
        note = NOTES[key][idx % len(NOTES[key])]
        if key == "newborn":
            c.member_ref = member_ref if idx % 2 == 0 else None
            c.events += [
                ("user", rng.choice(["Hi, I just had a baby two weeks ago and I need to add her to my insurance.",
                                     "How do I put my newborn son on my plan?", "We just had a baby. What do I need to do to get him covered?"]), {}),
                ("tool_call", None, {"name": "search_knowledge", "args": {"query": "add newborn to plan"}}),
                ("tool_result", None, {"name": "search_knowledge", "ok": True, "result": {"no_answer": True}}),
                ("assistant", "Congratulations! I don't have approved information on adding a new dependent. Would you like me to connect you with a specialist?", {}),
                ("user", "Yes, please.", {}),
            ]
            c.tools_used.append({"name": "search_knowledge", "ok": True, "summary": "Searched knowledge for 'add newborn to plan': no answer"})
            goal = GOALS["newborn"]
        elif key == "prior_auth":
            auth = rng.choice(sorted(AUTH_OWNERS))
            member_ref = AUTH_OWNERS[auth]
            c.member_ref = member_ref
            c.events.append(("user", f"I'm calling to check on a prior authorization, {auth}.", {}))
            _verify(c, member_ref)
            c.events += [("assistant", "I'm not able to look up authorization status myself, but a specialist can do that for you right away.", {}),
                         ("user", "Okay, go ahead.", {})]
            goal = f"You want to know the status of your prior authorization {auth}."
        elif key == "appeals":
            member_ref = "EVG-337120"
            c.member_ref = member_ref
            c.events.append(("user", "My claim was denied and I want to appeal. This is ridiculous.", {}))
            _verify(c, member_ref)
            _tool(c, "get_claim_status", {"claim_id": "C-31544"}, {"claim_id": "C-31544", "status": "denied", "denial_reason": "Out-of-network facility"},
                  "get_claim_status: status=denied, denial_reason=Out-of-network facility")
            c.events.append(("assistant", "I see claim C-31544 was denied because the facility was out of network. Appeals are handled by a specialist.", {}))
            goal = GOALS["appeals"]
        else:
            c.member_ref = None
            c.events.append(("user", "My doctor billed me twice for the same visit." if key == "billing_dispute" else "Can I just talk to a person?", {}))
            goal = GOALS[key]
        c.events += [
            ("tool_call", None, {"name": "escalate_to_human", "args": {"reason_category": category, "reason_detail": GAPS[key][0]}}),
            ("tool_result", None, {"name": "escalate_to_human", "ok": True, "result": {"status": "escalated"}}),
            ("assistant", HANDOFF, {}),
            ("system", f"Escalated: {category.replace('_', ' ')}", {"category": category}),
        ]
        sentiment_end = "frustrated" if key in ("appeals", "billing_dispute") else "neutral"
        c.escalation = {
            "category": category, "detail": GAPS[key][0], "disposition": "appeal_filed" if key == "appeals" else "resolved_by_human",
            "note": note, "assignee": ASSIGNEES[2] if key == "appeals" else ASSIGNEES[idx % 2],
            "packet": {
                "summary": f"Caller: {goal.removeprefix('You ').rstrip('.')}. The assistant could not complete this and escalated ({category.replace('_', ' ')}).",
                "intent": intent, "entities": {"member_ref": c.member_ref} if c.member_ref else {},
                "already_tried": [t["summary"] for t in c.tools_used],
                "escalation_reason": {"category": category, "detail": GAPS[key][0]},
                "sentiment": {"start": "neutral", "end": sentiment_end, "trend": "declining" if sentiment_end != "neutral" else "stable"},
                "suggested_next_action": "Help the caller with their request and record what you told them.",
                "caller_verified": bool(c.member_ref),
            },
        }
        c.analysis = {"outcome": "escalated", "intent": intent, "root_cause": root, "gap_summary": GAPS[key][idx % len(GAPS[key])],
                      "caller_goal": goal, "resolution_summary": note, "sentiment_start": "neutral", "sentiment_end": sentiment_end}
        return c
    c.analysis = {"outcome": "resolved", "intent": intent, "root_cause": "none", "gap_summary": "", "caller_goal": goal,
                  "resolution_summary": resolution, "sentiment_start": "neutral", "sentiment_end": "positive"}
    return c


def generate(today: date | None = None) -> list[SeedCall]:
    """123 calls over the 4 weeks ending yesterday; deterministic for a given `today`."""
    rng = random.Random(42)
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=28)
    pool = [i for i, n in MIX if i != "add_dependent_newborn" for _ in range(n)]
    rng.shuffle(pool)
    calls: list[SeedCall] = []
    counters: dict[str, int] = {}
    for week, total in enumerate(WEEKLY):
        intents = ["add_dependent_newborn"] * NEWBORN_WEEKLY[week]
        intents += [pool.pop() for _ in range(total - NEWBORN_WEEKLY[week])]
        rng.shuffle(intents)
        for intent in intents:
            day = start + timedelta(days=week * 7 + rng.randrange(7))
            when = datetime(day.year, day.month, day.day, rng.randrange(8, 18), rng.randrange(60), rng.randrange(60), tzinfo=timezone.utc)
            call = _build(intent, when, rng, counters)
            call.cost = round(rng.uniform(0.004, 0.012), 4)
            call.latency_ms = rng.randrange(650, 1400)
            calls.append(call)
    calls.sort(key=lambda c: c.started_at)
    return calls
