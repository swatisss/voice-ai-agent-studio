"""Seed definitions: tenants, tools, skills, agents, regression scenarios.

Spec: /demo-data/evergreen-health.md
"""
from __future__ import annotations

from typing import Any

MEMBERS_TENANT = "evergreen-members"
PHARMACY_TENANT = "evergreen-pharmacy"

TENANTS = [
    {"id": MEMBERS_TENANT, "name": "Evergreen Health · Member Services", "industry": "Health insurance"},
    {"id": PHARMACY_TENANT, "name": "Evergreen Health · Pharmacy Benefits", "industry": "Health insurance"},
]

_EMPTY: dict[str, Any] = {"type": "object", "properties": {}}

VERIFY_TOOL = {
    "name": "verify_member",
    "description": "Verify the caller's identity with member ID and date of birth. Required before any member-specific information.",
    "method": "POST", "url": "/mock/healthcare/verify",
    "parameters": {"type": "object", "properties": {
        "member_id": {"type": "string", "description": "Member ID as spoken, e.g. 482913 or EVG-482913"},
        "date_of_birth": {"type": "string", "description": "Date of birth in YYYY-MM-DD format"},
    }, "required": ["member_id", "date_of_birth"]},
    "requires_verification": False, "is_verification": True,
}

MEMBER_TOOLS = [
    VERIFY_TOOL,
    {"name": "get_benefits", "description": "Plan benefits for the verified member: deductible and out-of-pocket amounts met and remaining, and copays.",
     "method": "GET", "url": "/mock/healthcare/benefits", "parameters": _EMPTY, "requires_verification": True},
    {"name": "get_member_claims", "description": "List the verified member's recent claims (claim number, service, date, status).",
     "method": "GET", "url": "/mock/healthcare/claims", "parameters": _EMPTY, "requires_verification": True},
    {"name": "get_claim_status", "description": "Look up one claim of the verified member by claim number (e.g. C-20931).",
     "method": "GET", "url": "/mock/healthcare/claims/{claim_id}",
     "parameters": {"type": "object", "properties": {"claim_id": {"type": "string", "description": "Claim number like C-20931"}}, "required": ["claim_id"]},
     "requires_verification": True},
    {"name": "find_providers", "description": "Find in-network providers by specialty, optionally near a zip code.",
     "method": "GET", "url": "/mock/healthcare/providers",
     "parameters": {"type": "object", "properties": {
         "specialty": {"type": "string", "description": "e.g. dermatology, primary care, pediatrics"},
         "zip": {"type": "string", "description": "5-digit zip code"}}, "required": ["specialty"]}},
    {"name": "request_id_card", "description": "Order a replacement physical ID card for the verified member.",
     "method": "POST", "url": "/mock/healthcare/id-card",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string", "description": "lost, damaged or other"}}},
     "requires_verification": True},
]

PHARMACY_TOOLS = [
    VERIFY_TOOL,
    {"name": "check_formulary", "description": "Check whether a drug is covered: tier, 30-day copay, prior authorization and quantity limits.",
     "method": "GET", "url": "/mock/pharmacy/formulary",
     "parameters": {"type": "object", "properties": {"drug": {"type": "string", "description": "Generic or brand name"}}, "required": ["drug"]}},
    {"name": "get_refill_status", "description": "Refill status of the verified member's prescription by Rx number (e.g. RX-55102).",
     "method": "GET", "url": "/mock/pharmacy/refills/{rx_id}",
     "parameters": {"type": "object", "properties": {"rx_id": {"type": "string", "description": "Prescription number like RX-55102"}}, "required": ["rx_id"]},
     "requires_verification": True},
]

VERIFY_SKILL = {
    "name": "Identity verification",
    "description": "Any request that needs member-specific information.",
    "instructions": (
        "1. Ask for the caller's member ID and date of birth.\n"
        "2. Call verify_member with the member ID and the date of birth in YYYY-MM-DD format.\n"
        "3. If verified, thank them by first name and continue with their request. If not, ask them to repeat both once.\n"
        "4. Never read back the full member ID or date of birth."
    ),
    "required_tools": ["verify_member"],
    "escalate_when": "Verification fails twice.",
}

MEMBER_SKILLS = [
    VERIFY_SKILL,
    {"name": "Claim status", "description": "Caller asks whether a claim was paid, denied or is still processing.",
     "instructions": (
         "1. Verify identity first.\n"
         "2. Ask for the claim number. If they don't have it, call get_member_claims and confirm the claim by service and date.\n"
         "3. Call get_claim_status.\n"
         "4. In one or two sentences give the status, what the plan paid and what the member owes - or the expected decision date, or the denial reason.\n"
         "5. If the claim is denied, explain the reason and that appeals are handled by a specialist."),
     "required_tools": ["verify_member", "get_member_claims", "get_claim_status"],
     "escalate_when": "The caller disputes a denial or wants to file an appeal."},
    {"name": "Benefits and costs", "description": "Deductible, out-of-pocket maximum and copay questions.",
     "instructions": (
         "1. For general questions about how deductibles, copays or out-of-pocket maximums work, call search_knowledge.\n"
         "2. For the caller's own balances or copays, verify identity, then call get_benefits.\n"
         "3. Answer with the specific numbers: amount met, amount remaining, or the copay for the visit type asked about."),
     "required_tools": ["verify_member", "get_benefits"], "escalate_when": ""},
    {"name": "ID card", "description": "Lost, damaged or new member ID card.",
     "instructions": (
         "1. Verify identity.\n"
         "2. Mention the digital ID card is available right away in the Evergreen Health app.\n"
         "3. If they still want a physical card, call request_id_card and say it arrives in 7 to 10 business days at the address on file."),
     "required_tools": ["verify_member", "request_id_card"], "escalate_when": ""},
    {"name": "Find a provider", "description": "Caller needs an in-network doctor, specialist or facility.",
     "instructions": (
         "1. Ask what kind of doctor they need and their zip code.\n"
         "2. Call find_providers.\n"
         "3. Offer up to two options with name, practice and whether they accept new patients; give the phone number if asked.\n"
         "4. Remind HMO members that specialists need a referral from their primary care doctor."),
     "required_tools": ["find_providers"], "escalate_when": "No in-network provider is found for the needed specialty."},
    {"name": "Appeals and grievances", "description": "Caller wants to appeal a denial or file a complaint.",
     "instructions": (
         "1. Acknowledge the caller's frustration briefly.\n"
         "2. Verify identity and identify the claim (get_member_claims or get_claim_status) so the specialist has the details.\n"
         "3. Explain the denial reason in one sentence.\n"
         "4. Call escalate_to_human with reason_category policy_required."),
     "required_tools": ["verify_member", "get_claim_status"], "escalate_when": "Always, once the claim is identified."},
]

PHARMACY_SKILLS = [
    VERIFY_SKILL,
    {"name": "Drug coverage", "description": "Is a drug covered and what does it cost.",
     "instructions": "1. Ask for the drug name.\n2. Call check_formulary.\n3. Give the tier and 30-day copay, and mention prior authorization or quantity limits if they apply.",
     "required_tools": ["check_formulary"], "escalate_when": "The drug is not on the formulary and the caller needs an exception."},
    {"name": "Refill status", "description": "Caller asks about a prescription refill.",
     "instructions": "1. Verify identity.\n2. Ask for the Rx number.\n3. Call get_refill_status and explain refills remaining and the next eligible date; if none remain, explain a new prescription is needed.",
     "required_tools": ["verify_member", "get_refill_status"], "escalate_when": ""},
]

MEMBER_AGENT = {
    "name": "Member Services Agent",
    "description": "Claims, benefits, ID cards and provider search for Evergreen Health members.",
    "persona": {
        "name": "Ava", "voice": "aura-2-thalia-en",
        "greeting": "Thanks for calling Evergreen Health member services, this is Ava.",
        "disclosure": "I'm a virtual assistant, and this call may be recorded for quality. How can I help you today?",
        "style": "Warm, calm and concise. One question at a time. Plain language, no insurance jargon unless the caller uses it.",
    },
    "policy": {
        "rules": [
            "Verify identity with member ID and date of birth before sharing any member-specific information.",
            "When explaining a claim, give its status, what the plan paid, and what the member owes.",
            "Offer the 24/7 nurse line for health questions.",
        ],
        "escalate_when": [
            "The caller wants to file an appeal or grievance, or disputes a denial.",
            "The caller reports a provider billing error that needs investigation.",
        ],
        "never": [
            "Promise that a claim, appeal or authorization will be approved.",
            "Share information about anyone other than the verified member.",
        ],
        "max_turns": 16,
    },
}

PHARMACY_AGENT = {
    "name": "Pharmacy Benefits Agent",
    "description": "Drug coverage and refill questions for Evergreen Health members.",
    "persona": {
        "name": "Leo", "voice": "aura-2-apollo-en",
        "greeting": "Evergreen Health pharmacy benefits, this is Leo.",
        "disclosure": "I'm a virtual assistant, and this call may be recorded for quality. What can I help you with?",
        "style": "Friendly and efficient. One question at a time. Plain language.",
    },
    "policy": {
        "rules": ["Verify identity with member ID and date of birth before sharing prescription details."],
        "escalate_when": ["The caller needs a formulary exception or a prior authorization decision."],
        "never": ["Recommend changing, stopping or starting a medication."],
        "max_turns": 16,
    },
}


def _profile(name: str, member_id: str, dob: str, **extra: str) -> dict[str, str]:
    return {"name": name, "member_id": member_id, "date_of_birth": dob, **extra}


MEMBER_SCENARIOS = [
    {"name": "Claim paid", "caller_goal": "You want to know whether claim C-20931 was paid and how much you owe.",
     "caller_profile": _profile("Maria Lopez", "482913", "1986-04-12", claim_number="C-20931"), "expected": "resolved"},
    {"name": "Deductible remaining", "caller_goal": "You want to know how much of your deductible is left this year.",
     "caller_profile": _profile("Maria Lopez", "482913", "1986-04-12"), "expected": "resolved"},
    {"name": "Replace ID card", "caller_goal": "You lost your insurance card and want a replacement.",
     "caller_profile": _profile("James Carter", "337120", "1979-11-02"), "expected": "resolved"},
    {"name": "Find dermatologist", "caller_goal": "You want an in-network dermatologist near zip code 94110.",
     "caller_profile": _profile("Priya Nair", "559804", "1992-07-23", zip_code="94110"), "expected": "resolved"},
    {"name": "Specialist copay", "caller_goal": "You want to know your copay for a specialist visit.",
     "caller_profile": _profile("Daniel Kim", "801456", "2001-03-08"), "expected": "resolved"},
    {"name": "Appeal denied claim", "caller_goal": "Your surgery claim C-31544 was denied and you want to appeal it.",
     "caller_profile": _profile("James Carter", "337120", "1979-11-02", claim_number="C-31544"), "expected": "escalated"},
]
