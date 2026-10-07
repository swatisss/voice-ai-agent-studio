"""Synthetic business records behind the mock healthcare and insurance API.

Spec: /demo-data/members-and-claims.md, /api/mock-healthcare-api.md
Dates written T±n in the spec are relative to the day the process starts (or `reset()` is called).
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

PLANS = {
    "Evergreen Silver PPO": {"type": "PPO", "deductible": 1500, "oop_max": 6000,
                             "copays": {"primary_care": 30, "specialist": 35, "urgent_care": 60, "emergency_room": 250, "telehealth": 0},
                             "referral": False},
    "Evergreen Gold HMO": {"type": "HMO", "deductible": 500, "oop_max": 4000,
                           "copays": {"primary_care": 20, "specialist": 40, "urgent_care": 50, "emergency_room": 200, "telehealth": 0},
                           "referral": True},
    "Evergreen Bronze EPO": {"type": "EPO", "deductible": 4000, "oop_max": 8500,
                             "copays": {"primary_care": 45, "specialist": 75, "urgent_care": 90, "emergency_room": 400, "telehealth": 15},
                             "referral": False},
}

MEMBERS = {
    "EVG-482913": {"first_name": "Maria", "last_name": "Lopez", "dob": "1986-04-12", "plan": "Evergreen Silver PPO", "ded_met": 850, "oop_met": 1200, "email": "maria.lopez@example.com"},
    "EVG-337120": {"first_name": "James", "last_name": "Carter", "dob": "1979-11-02", "plan": "Evergreen Gold HMO", "ded_met": 500, "oop_met": 1450, "email": "james.carter@example.com"},
    "EVG-559804": {"first_name": "Priya", "last_name": "Nair", "dob": "1992-07-23", "plan": "Evergreen Silver PPO", "ded_met": 300, "oop_met": 410, "email": "priya.nair@example.com"},
    "EVG-610277": {"first_name": "Robert", "last_name": "Chen", "dob": "1958-01-30", "plan": "Evergreen Gold HMO", "ded_met": 500, "oop_met": 2980, "email": "robert.chen@example.com"},
    "EVG-725031": {"first_name": "Aisha", "last_name": "Okafor", "dob": "1990-09-15", "plan": "Evergreen Bronze EPO", "ded_met": 1120, "oop_met": 1120, "email": "aisha.okafor@example.com"},
    "EVG-801456": {"first_name": "Daniel", "last_name": "Kim", "dob": "2001-03-08", "plan": "Evergreen Silver PPO", "ded_met": 0, "oop_met": 60, "email": "daniel.kim@example.com"},
}

CLAIMS = {
    "C-20931": {"member": "EVG-482913", "type": "health", "service": "Office visit - dermatology", "provider": "Mission Dermatology", "service_date": "2026-09-10",
                "billed": 220.0, "status": "paid", "plan_paid": 185.0, "member_responsibility": 35.0, "paid_date": "2026-09-28",
                "notes": "Specialist copay applied.",
                "timeline": [{"date": "2026-09-10", "event": "Claim received"}, {"date": "2026-09-18", "event": "Claim reviewed"}, {"date": "2026-09-28", "event": "Claim paid"}],
                "next_step": "No action needed. Wait for the provider's bill before paying."},
    "C-20977": {"member": "EVG-482913", "type": "health", "service": "Lab work - lipid panel", "provider": "Quest Diagnostics", "service_date": "2026-09-18",
                "billed": 140.0, "status": "processing", "expected_decision_date_offset": 4,
                "timeline": [{"date": "2026-09-18", "event": "Claim received"}, {"date": "2026-09-25", "event": "In review"}],
                "next_step": "Expect a decision within a few days."},
    "C-31544": {"member": "EVG-337120", "type": "health", "service": "Emergency appendectomy", "provider": "Lakeside Surgical Center", "service_date": "2026-08-29",
                "billed": 18400.0, "status": "denied", "plan_paid": 0.0, "denial_reason": "Out-of-network facility",
                "appeal_deadline": "2027-02-25",
                "timeline": [{"date": "2026-08-29", "event": "Claim received"}, {"date": "2026-09-19", "event": "Claim denied: out-of-network facility"}],
                "next_step": "An appeals specialist can file an appeal before February 25, 2027."},
    "C-31602": {"member": "EVG-337120", "type": "health", "service": "Emergency room visit", "provider": "Bayview Medical Center", "service_date": "2026-08-29",
                "billed": 2150.0, "status": "paid", "plan_paid": 1950.0, "member_responsibility": 200.0, "paid_date": "2026-09-15",
                "notes": "Emergency room copay applied.",
                "timeline": [{"date": "2026-08-29", "event": "Claim received"}, {"date": "2026-09-15", "event": "Claim paid"}],
                "next_step": "No action needed."},
    "C-40210": {"member": "EVG-559804", "type": "health", "service": "MRI lumbar spine", "provider": "Bay Imaging", "service_date": "2026-09-22",
                "billed": 1850.0, "status": "pending information",
                "notes": "Provider was asked to send authorization number PA-77812.",
                "timeline": [{"date": "2026-09-22", "event": "Claim received"}, {"date": "2026-09-29", "event": "Waiting for the provider's authorization number"}],
                "next_step": "The provider has been asked for the missing information; nothing is needed from the member."},
    "C-41007": {"member": "EVG-610277", "type": "health", "service": "Physical therapy, 6 visits", "provider": "Harbor Physical Therapy", "service_date": "2026-09-05",
                "billed": 900.0, "status": "paid", "plan_paid": 660.0, "member_responsibility": 240.0, "paid_date": "2026-09-25",
                "notes": "6 x $40 specialist copay.",
                "timeline": [{"date": "2026-09-05", "event": "Claim received"}, {"date": "2026-09-25", "event": "Claim paid"}],
                "next_step": "No action needed."},
    "C-52230": {"member": "EVG-725031", "type": "health", "service": "Urgent care visit", "provider": "CityCare Urgent Care", "service_date": "2026-09-30",
                "billed": 310.0, "status": "paid", "plan_paid": 220.0, "member_responsibility": 90.0, "paid_date": "2026-10-03",
                "notes": "Urgent care copay applied.",
                "timeline": [{"date": "2026-09-30", "event": "Claim received"}, {"date": "2026-10-03", "event": "Claim paid"}],
                "next_step": "No action needed."},
    "C-60012": {"member": "EVG-337120", "type": "motor", "service": "Windscreen replacement", "provider": "Clearview Glass", "service_date": "2026-09-02",
                "billed": 410.0, "status": "paid", "plan_paid": 410.0, "member_responsibility": 0.0, "paid_date": "2026-09-12",
                "notes": "Glass cover, no excess.",
                "timeline": [{"date": "2026-09-02", "event": "Claim received"}, {"date": "2026-09-05", "event": "Claim approved"}, {"date": "2026-09-12", "event": "Claim paid"}],
                "next_step": "No action needed."},
}

PRIOR_AUTHS = {
    "PA-77812": {"member": "EVG-559804", "service": "MRI lumbar spine", "status": "approved", "decision_date": "2026-09-20", "valid_through": "2026-12-20"},
    "PA-77930": {"member": "EVG-725031", "service": "Knee arthroscopy", "status": "pending clinical review", "expected_decision_date_offset": 3},
    "PA-78001": {"member": "EVG-610277", "service": "CPAP device", "status": "denied", "decision_date": "2026-09-26",
                 "notes": "Insufficient documentation; the provider may resubmit with a sleep study."},
}

PROVIDERS = [
    {"name": "Dr. Elena Ruiz", "specialty": "Dermatology", "practice": "Mission Dermatology", "address": "2400 Mission St, San Francisco, CA", "zip": "94110", "phone": "(415) 555-0110", "accepting_new_patients": True},
    {"name": "Dr. Samuel Park", "specialty": "Dermatology", "practice": "Sunset Skin Clinic", "address": "1801 Irving St, San Francisco, CA", "zip": "94122", "phone": "(415) 555-0127", "accepting_new_patients": False},
    {"name": "Dr. Grace Liu", "specialty": "Primary care", "practice": "Bayview Family Medicine", "address": "5000 3rd St, San Francisco, CA", "zip": "94124", "phone": "(415) 555-0133", "accepting_new_patients": True},
    {"name": "Dr. Marcus Bell", "specialty": "Orthopedics", "practice": "Lakeside Orthopedics", "address": "2100 Webster St, San Francisco, CA", "zip": "94115", "phone": "(415) 555-0148", "accepting_new_patients": True},
    {"name": "Harbor Mental Health Associates", "specialty": "Behavioral health", "practice": "Harbor Mental Health", "address": "1035 Market St, San Francisco, CA", "zip": "94103", "phone": "(415) 555-0156", "accepting_new_patients": True},
    {"name": "Dr. Hannah Wright", "specialty": "Pediatrics", "practice": "Little Steps Pediatrics", "address": "3150 18th St, San Francisco, CA", "zip": "94110", "phone": "(415) 555-0161", "accepting_new_patients": True},
    {"name": "Dr. Naomi Reyes", "specialty": "Dentistry", "practice": "Mission Family Dental", "address": "2480 Mission St, San Francisco, CA", "zip": "94110", "phone": "(415) 555-0172", "accepting_new_patients": True},
]

# benefit -> (covered, annual_limit, copay_percent, waiting_period_days, pre_authorization_required, notes)
BENEFITS: dict[str, dict[str, tuple]] = {
    "Evergreen Silver PPO": {
        "inpatient": (True, None, 0, 0, True, "No annual limit."), "outpatient": (True, 5000, 10, 0, False, ""),
        "maternity": (True, 10000, 0, 365, True, ""), "dental": (True, 800, 20, 90, False, ""), "optical": (True, 300, 0, 30, False, ""),
        "mental_health": (True, 4000, 0, 0, False, ""), "physiotherapy": (True, 1200, 0, 0, False, "A referral is needed."),
    },
    "Evergreen Gold HMO": {
        "inpatient": (True, None, 0, 0, True, "No annual limit."), "outpatient": (True, 8000, 0, 0, False, ""),
        "maternity": (True, 15000, 0, 365, True, ""), "dental": (True, 1500, 10, 60, False, ""), "optical": (True, 500, 0, 30, False, ""),
        "mental_health": (True, 6000, 0, 0, False, ""), "physiotherapy": (True, 2000, 0, 0, False, "A referral is needed."),
    },
    "Evergreen Bronze EPO": {
        "inpatient": (True, None, 0, 0, True, "No annual limit."), "outpatient": (True, 2000, 20, 0, False, ""),
        "maternity": (True, 5000, 0, 365, True, ""), "dental": (False, None, None, None, False, "Not covered on this plan."),
        "optical": (False, None, None, None, False, "Not covered on this plan."), "mental_health": (True, 2000, 0, 0, False, ""),
        "physiotherapy": (True, 600, 0, 0, False, "A referral is needed."),
    },
}
BENEFIT_ALIASES = {
    "dentistry": "dental", "dentist": "dental", "teeth": "dental", "eye": "optical", "eyes": "optical", "glasses": "optical", "vision": "optical",
    "pregnancy": "maternity", "mental": "mental_health", "therapy": "mental_health", "counselling": "mental_health", "counseling": "mental_health",
    "physio": "physiotherapy", "hospital": "inpatient", "outpatients": "outpatient",
}
USAGE = {
    "EVG-482913": {"outpatient": 1850, "dental": 320, "mental_health": 600},
    "EVG-559804": {"dental": 100, "outpatient": 410},
    "EVG-801456": {"outpatient": 60},
}

DOCUMENT_TYPES = {
    "policy_schedule": ("Policy schedule", ("health", "motor"), ("email", "download", "post")),
    "policy_wording": ("Policy wording", ("health", "motor"), ("email", "download", "post")),
    "membership_card": ("Membership card", ("health",), ("email", "download", "post")),
    "certificate_of_insurance": ("Certificate of insurance", ("motor",), ("email", "download", "post")),
    "premium_invoice": ("Premium invoice", ("health", "motor"), ("email", "download", "post")),
    "tax_certificate": ("Annual premium statement", ("health",), ("email", "download", "post")),
    "green_card": ("Green Card (international motor insurance certificate)", ("motor",), ("email", "download")),
}
GREEN_CARD_COUNTRIES = ["Austria", "Belgium", "Denmark", "France", "Germany", "Greece", "Ireland", "Italy", "Netherlands", "Norway", "Portugal", "Spain", "Sweden", "Switzerland", "Turkey"]
DOCUMENT_ETA = {"email": "within 15 minutes", "download": "instant", "post": "5-7 business days"}

# member-facing renewal quotes: policy -> (renewal premium, reasons, options)
QUOTES = {
    "MP-200415": (738.70, ["Repair cost inflation", "One claim in the last 12 months"],
                  [{"name": "Renew as is", "premium": 738.70, "notes": "Same cover and excess"},
                   {"name": "Increase voluntary excess to $500", "premium": 689.30, "notes": "Saves $49.40 a year"}]),
    "HP-100231": (2651.00, ["Medical cost inflation (3.2%)", "Moving into the 35-39 age band"],
                  [{"name": "Renew as is", "premium": 2651.00, "notes": "Monthly payments continue"},
                   {"name": "Pay annually", "premium": 2518.45, "notes": "5% discount for paying once a year"}]),
    "HP-100790": (3214.00, ["Medical cost inflation (3.2%)"], [{"name": "Renew as is", "premium": 3214.00, "notes": "Monthly payments continue"}]),
    "HP-100412": (3214.00, ["Medical cost inflation (3.2%)"], [{"name": "Renew as is", "premium": 3214.00, "notes": "Monthly payments continue"}]),
}

ONBOARDING_STEPS = {
    "confirm_contact_details": "Confirm contact details",
    "communication_preferences": "Choose communication preferences",
    "register_online_account": "Register your online account",
    "download_membership_card": "Download your membership card",
    "choose_primary_provider": "Choose a primary provider",
    "review_waiting_periods": "Review your waiting periods",
}
COMMUNICATION_PREFERENCES = ("email", "sms", "post")

AUTH_LIMITS = {
    "claims_handler": {"inpatient": 5000, "outpatient": 2000, "dental": 1000},
    "senior_handler": {"inpatient": 25000, "outpatient": 10000, "dental": 5000},
    "team_leader": {"inpatient": 100000, "outpatient": 50000, "dental": 20000},
    "claims_manager": {"inpatient": 250000, "outpatient": 100000, "dental": 50000},
}
CONTACTS = {
    "fraud": ("Special Investigations Unit", "4410", "Mon-Fri 8:00-18:00", "siu@evergreen.example"),
    "complaints": ("Customer Resolution Team", "4120", "Mon-Fri 8:00-18:00", "resolution@evergreen.example"),
    "legal": ("Legal & Compliance", "4600", "Mon-Fri 9:00-17:00", "legal@evergreen.example"),
    "data_protection": ("Privacy Office", "4700", "Mon-Fri 9:00-17:00", "privacy@evergreen.example"),
    "it_service_desk": ("IT Service Desk", "4000", "24/7", "servicedesk@evergreen.example"),
    "medical_director": ("Clinical Governance", "4850", "Mon-Fri 9:00-17:00", "clinical@evergreen.example"),
}

NURSE_LINE = "1-800-555-0142"

# ---------------------------------------------------------------- mutable, date-relative state
POLICIES: dict[str, dict[str, Any]] = {}
ONBOARDING: dict[str, dict[str, Any]] = {}
DOCUMENT_REQUESTS: list[dict[str, Any]] = []
RENEWAL_DECISIONS: list[dict[str, Any]] = []
_counters = {"doc": 0, "renewal": 0}


def today() -> date:
    return date.today()


def rel(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


def reset() -> None:
    """Rebuild the date-relative and mutable records (process start, tests, `seed --reset`)."""
    def pol(member, ptype, product, status, start, end, premium, freq, pay, nxt, overdue=0.0, grace=None, **extra):  # noqa: ANN001, ANN003
        return {"member": member, "type": ptype, "product": product, "status": status, "start_date": rel(start), "end_date": rel(end),
                "renewal_date": rel(end), "annual_premium": premium, "payment_frequency": freq, "payment_status": pay,
                "next_payment_date": rel(nxt) if nxt is not None else None, "overdue_amount": overdue,
                "grace_period_ends": rel(grace) if grace is not None else None, "cover_level": product, "renewal_status": "pending", **extra}

    POLICIES.clear()
    POLICIES.update({
        "HP-100231": pol("EVG-482913", "health", "Evergreen Silver PPO", "active", -340, 25, 2548.80, "monthly", "up_to_date", 9),
        "HP-100412": pol("EVG-337120", "health", "Evergreen Gold HMO", "active", -280, 85, 3120.00, "monthly", "up_to_date", 12),
        "MP-200415": pol("EVG-337120", "motor", "Evergreen Motor Comprehensive", "active", -352, 13, 684.00, "annual", "up_to_date", None,
                         vehicle="Toyota Corolla 2020, reg DEMO-4821", voluntary_excess=250),
        "HP-100655": pol("EVG-559804", "health", "Evergreen Silver PPO", "active", -200, 165, 2548.80, "monthly", "up_to_date", 20),
        "HP-100790": pol("EVG-610277", "health", "Evergreen Gold HMO", "active", -300, 55, 3120.00, "monthly", "overdue", -7, overdue=212.40, grace=7),
        "HP-100877": pol("EVG-725031", "health", "Evergreen Bronze EPO", "active", -7, 358, 1980.00, "monthly", "up_to_date", 23),
        "HP-100901": pol("EVG-801456", "health", "Evergreen Silver PPO", "active", -21, 344, 2548.80, "monthly", "up_to_date", 9),
    })
    ONBOARDING.clear()
    ONBOARDING.update({
        "EVG-725031": {"policy_id": "HP-100877", "steps": {**{s: "pending" for s in ONBOARDING_STEPS}, "confirm_contact_details": "done"}, "preferences": None},
        "EVG-801456": {"policy_id": "HP-100901", "steps": {**{s: "pending" for s in ONBOARDING_STEPS},
                                                           "confirm_contact_details": "done", "register_online_account": "done", "download_membership_card": "done"}, "preferences": None},
    })
    DOCUMENT_REQUESTS.clear()
    RENEWAL_DECISIONS.clear()
    _counters.update(doc=0, renewal=0)


def next_id(kind: str) -> int:
    _counters[kind] += 1
    return _counters[kind]


def snapshot() -> dict[str, Any]:  # for tests
    return copy.deepcopy({"policies": POLICIES, "onboarding": ONBOARDING})


reset()
