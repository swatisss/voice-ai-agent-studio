"""Deterministic synthetic call history for the Customer Care agent (Northgate Health).

Spec: /demo-data/call-history.md
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from voiceai.mock import data as mock

GREETING = ("Thanks for calling Northgate Health, this is Olivia. I'm a virtual assistant, and this call may be recorded for quality and training. "
            "How can I help you today?")
HANDOFF = "I'm connecting you with a colleague who will have all the details, so you won't need to repeat yourself."
ASSIGNEES = ["Priya (Member Services)", "Callum (Member Services)", "Joanne (Customer Relations)"]

MIX = [  # (intent, count)
    ("policy_status", 14), ("payment_question", 26), ("document_request", 16), ("coverage_question", 20), ("gp_booking", 6),
    ("add_dependent_newborn", 14), ("prior_auth_status", 9), ("complaint", 8), ("cancellation", 3),
    ("speak_to_person", 4), ("abandoned", 3),
]
WEEKLY = [27, 30, 32, 34]
NEWBORN_WEEKLY = [3, 3, 4, 4]

ESCALATED = {
    "add_dependent_newborn": ("knowledge_gap", "missing_knowledge", "newborn"),
    "prior_auth_status": ("capability_gap", "missing_skill", "prior_auth"),
    "complaint": ("policy_required", "policy_required", "complaints"),
    "cancellation": ("policy_required", "policy_required", "cancellation"),
    "speak_to_person": ("caller_requested", "caller_requested", "caller_requested"),
}

CLUSTERS = {
    "newborn": ("Adding a newborn to the policy", "Callers want to know how and when to add a new baby to their health insurance; no approved article exists."),
    "prior_auth": ("Pre-authorisation status", "Callers ask member services whether a pre-authorisation is approved; the agent has no lookup tool."),
    "complaints": ("Complaints", "Callers want to make a formal complaint, which policy routes to customer relations."),
    "cancellation": ("Cancelling a policy", "Callers want to cancel; cancellations are handled by a person."),
    "caller_requested": ("Asked for a person", "Callers asked for a person at the start of the call."),
}

GAPS = {
    "newborn": ["How to add a newborn baby to an existing health insurance policy", "Deadline and medical questions for adding a new baby to the policy",
                "Adding a newborn to the policy after the birth"],
    "prior_auth": ["Checking whether a pre-authorisation has been approved", "Status of a pending pre-authorisation for surgery"],
    "complaints": ["Making a formal complaint about claim handling"],
    "cancellation": ["Cancelling a health insurance policy"],
    "caller_requested": ["Caller asked for a person without a specific unmet need"],
}

NOTES = {
    "newborn": [
        "Explained a newborn can be added within 3 months of birth with no medical questions; cover starts from the date we are told. "
        "Added the baby to the policy; new premium from the next collection.",
        "Added baby to the family policy by phone. Told caller the membership certificate is reissued within 5 working days and the baby shares the family excess.",
        "Told caller to add the baby within 3 months of birth to avoid medical questions; after that the baby joins on moratorium terms.",
        "Caller asked if the baby's hospital stay at birth is covered - no, normal childbirth is not covered; cover starts once the baby is added.",
        "Added newborn on caller's behalf at the child rate; sent an updated premium statement by email.",
    ],
    "prior_auth": [
        "Looked up the pre-authorisation: pending, waiting for the consultant's procedure code; decision expected within 2 working days.",
        "Pre-authorisation approved; gave the code, what it covers and the valid-until date. Caller can book.",
        "Pre-authorisation declined as the condition is excluded; explained the exclusion and the customer relations route.",
    ],
    "complaints": [
        "Logged a formal complaint; acknowledgment within 5 working days and a final response within 8 weeks, after which the Financial Ombudsman Service can review.",
        "Resolved the complaint on the call with an apology; sent a summary resolution communication.",
    ],
    "cancellation": ["Cancelled within the 21-day cooling-off period with a full refund; no claims had been made."],
    "caller_requested": ["Answered general questions about the policy; no further action needed."],
}

GOALS = {
    "newborn": "You recently had a baby and want to know how to add the baby to your health insurance.",
    "complaints": "You are unhappy with how your claim was handled and want to make a complaint.",
    "cancellation": "You want to cancel your health insurance policy.",
    "caller_requested": "You want to speak with a person.",
}

DOCUMENTS = [("membership_certificate", "membership certificate"), ("membership_card", "membership card"), ("premium_statement", "premium statement"),
             ("policy_guide", "policy guide")]

AUTH_OWNERS = {"PA-500955": "NGH-638405", "PA-500812": "NGH-410237", "PA-501020": "NGH-522918"}
HEALTH_MEMBERS = ["NGH-410237", "NGH-522918", "NGH-638405", "NGH-714560", "NGH-805193"]


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
    return f"{d.day} {d:%B} {d.year}"


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B}"


def _verify(c: SeedCall, member_ref: str) -> None:
    m = mock.MEMBERS[member_ref]
    c.events += [
        ("assistant", "I can help with that. Can I have your membership number and date of birth?", {}),
        ("user", f"Sure, it's {member_ref.split('-')[1]}, {_spoken_dob(m['dob'])}.", {}),
        ("tool_call", None, {"name": "verify_member", "args": {"member_id": member_ref.split('-')[1], "date_of_birth": m["dob"]}}),
        ("tool_result", None, {"name": "verify_member", "ok": True, "result": {"verified": True, "member_ref": member_ref, "first_name": m["first_name"]}}),
    ]
    c.tools_used.append({"name": "verify_member", "ok": True, "summary": "verify_member: verified=True"})


def _tool(c: SeedCall, name: str, args: dict[str, Any], result: dict[str, Any], summary: str) -> None:
    c.events += [("tool_call", None, {"name": name, "args": args}), ("tool_result", None, {"name": name, "ok": True, "result": result})]
    c.tools_used.append({"name": name, "ok": True, "summary": summary})


def _health_policy(member_ref: str) -> tuple[str, dict[str, Any]]:
    return next((i, p) for i, p in mock.POLICIES.items() if p["member"] == member_ref and p["type"] == "health")


def _build(intent: str, when: datetime, rng: random.Random, counters: dict[str, int]) -> SeedCall:  # noqa: C901, PLR0915
    member_ref = rng.choice(HEALTH_MEMBERS)
    c = SeedCall(started_at=when, intent=intent, outcome="resolved", member_ref=member_ref)
    c.events.append(("assistant", GREETING, {"greeting": True}))
    idx = counters.setdefault(intent, 0)
    counters[intent] += 1
    bye = ("assistant", "Thank you for calling Northgate Health. Take care!", {})

    if intent == "policy_status":
        pid, pol = _health_policy(member_ref)
        c.events.append(("user", rng.choice(["Hi, is my policy still active, and when does it renew?", "Can you tell me my excess and when my policy renews?"]), {}))
        _verify(c, member_ref)
        _tool(c, "get_member_policies", {}, {"policies": [{"policy_id": pid, "status": pol["status"], "renewal_date": pol["renewal_date"]}]}, "get_member_policies: 1 policies")
        _tool(c, "get_policy_details", {"policy_id": pid}, {"policy_id": pid, "status": pol["status"], "cover": {"excess": pol["excess"]}},
              f"get_policy_details: policy_id={pid}, status={pol['status']}")
        if pol["status"] == "payment_missed":
            ans = f"Your {pol['product']} policy is suspended because this month's payment was missed; it renews on {_day(pol['renewal_date'])}."
        else:
            ans = f"Your {pol['product']} policy is active and renews on {_day(pol['renewal_date'])}. Your excess is £{pol['excess']} per person each policy year."
        c.events += [("assistant", ans, {}), ("user", "Great, thanks.", {}), bye]
        goal, resolution = "You want to know if your policy is active, your excess and when it renews.", ans
    elif intent == "payment_question":
        pid, _pol = _health_policy(member_ref)
        pay = mock.PAYMENTS[pid]
        c.events.append(("user", rng.choice(["When is my next payment taken?", "How much am I paying each month?", "Did my last Direct Debit go through?"]), {}))
        _verify(c, member_ref)
        _tool(c, "get_payments", {"policy_id": pid}, {"policy_id": pid, "status": pay["status"], "monthly_amount": pay["amount"],
                                                      "next_collection_date": pay["next_collection_date"]}, f"get_payments: status={pay['status']}")
        if pay["status"] == "missed":
            ans = f"This month's payment of £{pay['missed_amount']:.2f} was missed. If it's paid by {_day(pay['reinstate_by'])}, your cover continues with no gap."
        else:
            ans = f"You pay £{pay['amount']:.2f} a month by Direct Debit, and the next payment is taken on {_day(pay['next_collection_date'])}."
        c.events += [("assistant", ans, {}), ("user", "Okay, that's all. Thanks!", {}), bye]
        goal, resolution = "You want to know about your monthly payment.", ans
    elif intent == "document_request":
        pid, _pol = _health_policy(member_ref)
        dtype, title = DOCUMENTS[idx % len(DOCUMENTS)]
        c.events.append(("user", f"Can you email me my {title}?", {}))
        _verify(c, member_ref)
        _tool(c, "request_document", {"policy_id": pid, "document_type": dtype, "delivery": "email"},
              {"request_id": f"DOC-{800 + idx}", "status": "queued", "eta": "within 15 minutes"}, f"request_document: request_id=DOC-{800 + idx}, status=queued")
        ans = f"I've emailed your {title} to the address we have for you. It should arrive within 15 minutes."
        c.events += [("assistant", ans, {}), ("user", "Thanks, that's all.", {}), bye]
        goal, resolution = f"You want your {title} emailed to you.", ans
    elif intent == "coverage_question" and idx % 2 == 1:
        member_ref = "NGH-917362" if idx % 4 == 1 else "NGH-638405"
        c.member_ref = member_ref
        pid = next(i for i, p in mock.POLICIES.items() if p["member"] == member_ref and p["type"] == "cash_plan")
        level = mock.POLICIES[pid]["level"]
        benefit = ["dental", "optical", "therapies"][idx % 3]
        limit = mock.CASH_PLAN_LEVELS[level][benefit]
        used = mock.CASH_PLAN_USAGE.get(member_ref, {}).get(benefit, 0)
        c.events.append(("user", f"How much {benefit} cover have I got left on my cash plan?", {}))
        _verify(c, member_ref)
        _tool(c, "get_cash_plan_benefits", {"policy_id": pid},
              {"policy_id": pid, "level": level, "benefits": [{"benefit": benefit, "yearly_limit": limit, "used": used, "remaining": limit - used}]},
              f"get_cash_plan_benefits: {benefit} remaining={limit - used}")
        ans = f"You have £{limit - used} of your £{limit} {benefit} limit left this year."
        c.events += [("assistant", ans, {}), ("user", "Thanks, that's clear.", {}), bye]
        goal, resolution = f"You want to know how much {benefit} cover is left on your cash plan.", ans
    elif intent == "coverage_question":
        pid, pol = _health_policy(member_ref)
        hospital_list = mock.HOSPITAL_LISTS[pol["hospital_list"]][1]
        c.events.append(("user", rng.choice(["Which hospitals can I use on my policy?", "Is physiotherapy covered on my policy?", "What does my outpatient limit cover?"]), {}))
        _verify(c, member_ref)
        _tool(c, "get_policy_details", {"policy_id": pid}, {"policy_id": pid, "cover": {"hospital_list": hospital_list, "outpatient_limit": pol["outpatient_limit"]}},
              f"get_policy_details: policy_id={pid}")
        ans = f"Your policy uses the {hospital_list.split(':')[0]}."
        if pol["outpatient_limit"] == "unlimited":
            ans += " Outpatient consultations, tests and therapies have no yearly limit."
        elif pol["outpatient_limit"]:
            ans += f" Outpatient consultations, tests and therapies are covered up to £{int(pol['outpatient_limit']):,} a year."
        else:
            ans += " Essentials pays for treatment once you have a diagnosis."
        c.events += [("assistant", ans, {}), ("user", "Thanks, that's clear.", {}), bye]
        goal, resolution = "You want to know which hospitals and outpatient care your policy covers.", ans
    elif intent == "gp_booking":
        member_ref = "NGH-410237"
        c.member_ref = member_ref
        when_day = when.date() + timedelta(days=1)
        c.events.append(("user", rng.choice(["Can I book a video GP appointment for tomorrow?", "I need to speak to a GP, can you book me in?"]), {}))
        _verify(c, member_ref)
        _tool(c, "get_gp_slots", {"type": "gp", "format": "video"},
              {"slots": [{"slot_id": "GP-109", "date": when_day.isoformat(), "time": "09:00", "format": "video"}]}, "get_gp_slots: 1 slots")
        _tool(c, "book_gp_appointment", {"slot_id": "GP-109", "reason": "sore throat"}, {"booking_id": f"GPB-{700 + idx}", "date": when_day.isoformat(), "time": "09:00"},
              f"book_gp_appointment: booking_id=GPB-{700 + idx}")
        ans = f"You're booked for a video GP appointment on {when_day.day} {when_day:%B} at 9am. You'll get a text with the link 15 minutes before."
        c.events += [("assistant", ans, {}), ("user", "Brilliant, thank you.", {}), bye]
        goal, resolution = "You want a video GP appointment.", ans
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
                ("user", rng.choice(["Hi, I had a baby two weeks ago and I need to add her to my health insurance.",
                                     "How do I put my newborn son on my policy?", "We've just had a baby. What do I need to do to get him covered?"]), {}),
                ("tool_call", None, {"name": "search_knowledge", "args": {"query": "add newborn baby to policy"}}),
                ("tool_result", None, {"name": "search_knowledge", "ok": True, "result": {"no_answer": True}}),
                ("assistant", "Congratulations! I don't have approved information on adding a new baby to a policy. Shall I put you through to a colleague?", {}),
                ("user", "Yes, please.", {}),
            ]
            c.tools_used.append({"name": "search_knowledge", "ok": True, "summary": "Searched knowledge for 'add newborn baby to policy': no answer"})
            goal = GOALS["newborn"]
        elif key == "prior_auth":
            auth = rng.choice(sorted(AUTH_OWNERS))
            member_ref = AUTH_OWNERS[auth]
            c.member_ref = member_ref
            c.events.append(("user", f"I'm calling to check whether my pre-authorisation {auth} has been approved.", {}))
            _verify(c, member_ref)
            c.events += [("assistant", "I'm not able to look up pre-authorisations myself, but a colleague can check that for you right away.", {}),
                         ("user", "Okay, go ahead.", {})]
            goal = f"You want to know the status of your pre-authorisation {auth}."
        elif key == "complaints":
            member_ref = "NGH-714560"
            c.member_ref = member_ref
            c.events.append(("user", "I want to make a complaint. My claim took weeks and then it was declined.", {}))
            _verify(c, member_ref)
            c.events.append(("assistant", "I'm sorry to hear that. I'll pass your complaint to our customer relations team with the details.", {}))
            goal = GOALS["complaints"]
        else:
            c.member_ref = None
            c.events.append(("user", "I'd like to cancel my policy." if key == "cancellation" else "Can I just talk to a person?", {}))
            goal = GOALS[key]
        c.events += [
            ("tool_call", None, {"name": "escalate_to_human", "args": {"reason_category": category, "reason_detail": GAPS[key][0]}}),
            ("tool_result", None, {"name": "escalate_to_human", "ok": True, "result": {"status": "escalated"}}),
            ("assistant", HANDOFF, {}),
            ("system", f"Escalated: {category.replace('_', ' ')}", {"category": category}),
        ]
        sentiment_end = "frustrated" if key == "complaints" else "neutral"
        c.escalation = {
            "category": category, "detail": GAPS[key][0], "disposition": "complaint_logged" if key == "complaints" else "resolved_by_human",
            "note": note, "assignee": ASSIGNEES[2] if key == "complaints" else ASSIGNEES[idx % 2],
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
