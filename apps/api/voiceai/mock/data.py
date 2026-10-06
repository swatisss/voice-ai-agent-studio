"""Synthetic business records behind the mock healthcare API.

Spec: /demo-data/members-and-claims.md
"""
from __future__ import annotations

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
    "EVG-482913": {"first_name": "Maria", "last_name": "Lopez", "dob": "1986-04-12", "plan": "Evergreen Silver PPO", "ded_met": 850, "oop_met": 1200},
    "EVG-337120": {"first_name": "James", "last_name": "Carter", "dob": "1979-11-02", "plan": "Evergreen Gold HMO", "ded_met": 500, "oop_met": 1450},
    "EVG-559804": {"first_name": "Priya", "last_name": "Nair", "dob": "1992-07-23", "plan": "Evergreen Silver PPO", "ded_met": 300, "oop_met": 410},
    "EVG-610277": {"first_name": "Robert", "last_name": "Chen", "dob": "1958-01-30", "plan": "Evergreen Gold HMO", "ded_met": 500, "oop_met": 2980},
    "EVG-725031": {"first_name": "Aisha", "last_name": "Okafor", "dob": "1990-09-15", "plan": "Evergreen Bronze EPO", "ded_met": 1120, "oop_met": 1120},
    "EVG-801456": {"first_name": "Daniel", "last_name": "Kim", "dob": "2001-03-08", "plan": "Evergreen Silver PPO", "ded_met": 0, "oop_met": 60},
}

CLAIMS = {
    "C-20931": {"member": "EVG-482913", "service": "Office visit - dermatology", "provider": "Mission Dermatology", "service_date": "2026-09-10",
                "billed": 220.0, "status": "paid", "plan_paid": 185.0, "member_responsibility": 35.0, "paid_date": "2026-09-28",
                "notes": "Specialist copay applied."},
    "C-20977": {"member": "EVG-482913", "service": "Lab work - lipid panel", "provider": "Quest Diagnostics", "service_date": "2026-09-18",
                "billed": 140.0, "status": "processing", "expected_decision_date": "2026-10-10"},
    "C-31544": {"member": "EVG-337120", "service": "Emergency appendectomy", "provider": "Lakeside Surgical Center", "service_date": "2026-08-29",
                "billed": 18400.0, "status": "denied", "plan_paid": 0.0, "denial_reason": "Out-of-network facility",
                "appeal_deadline": "2027-02-25"},
    "C-31602": {"member": "EVG-337120", "service": "Emergency room visit", "provider": "Bayview Medical Center", "service_date": "2026-08-29",
                "billed": 2150.0, "status": "paid", "plan_paid": 1950.0, "member_responsibility": 200.0, "paid_date": "2026-09-15",
                "notes": "Emergency room copay applied."},
    "C-40210": {"member": "EVG-559804", "service": "MRI lumbar spine", "provider": "Bay Imaging", "service_date": "2026-09-22",
                "billed": 1850.0, "status": "pending information",
                "notes": "Provider was asked to send authorization number PA-77812."},
    "C-41007": {"member": "EVG-610277", "service": "Physical therapy, 6 visits", "provider": "Harbor Physical Therapy", "service_date": "2026-09-05",
                "billed": 900.0, "status": "paid", "plan_paid": 660.0, "member_responsibility": 240.0, "paid_date": "2026-09-25",
                "notes": "6 x $40 specialist copay."},
    "C-52230": {"member": "EVG-725031", "service": "Urgent care visit", "provider": "CityCare Urgent Care", "service_date": "2026-09-30",
                "billed": 310.0, "status": "paid", "plan_paid": 220.0, "member_responsibility": 90.0, "paid_date": "2026-10-03",
                "notes": "Urgent care copay applied."},
}

PRIOR_AUTHS = {
    "PA-77812": {"member": "EVG-559804", "service": "MRI lumbar spine", "status": "approved", "decision_date": "2026-09-20", "valid_through": "2026-12-20"},
    "PA-77930": {"member": "EVG-725031", "service": "Knee arthroscopy", "status": "pending clinical review", "expected_decision_date": "2026-10-09"},
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
]

FORMULARY = {
    "atorvastatin": {"covered": True, "tier": "1", "copay_30_day": 5, "prior_auth_required": False, "quantity_limit": None, "alternatives": []},
    "sertraline": {"covered": True, "tier": "1", "copay_30_day": 5, "prior_auth_required": False, "quantity_limit": None, "alternatives": []},
    "apixaban": {"covered": True, "tier": "2", "copay_30_day": 40, "prior_auth_required": False, "quantity_limit": None, "alternatives": [], "brand": "Eliquis"},
    "semaglutide": {"covered": True, "tier": "3", "copay_30_day": 75, "prior_auth_required": True, "quantity_limit": "4 pens per 28 days", "alternatives": [], "brand": "Ozempic"},
    "adalimumab": {"covered": True, "tier": "specialty", "copay_30_day": 150, "prior_auth_required": True, "quantity_limit": None, "alternatives": [], "brand": "Humira"},
}

REFILLS = {
    "RX-55102": {"member": "EVG-482913", "drug": "atorvastatin 20 mg", "refills_remaining": 3, "last_fill_date": "2026-09-20", "next_eligible_date": "2026-10-15", "pharmacy": "Evergreen Mail Pharmacy"},
    "RX-55170": {"member": "EVG-610277", "drug": "apixaban 5 mg", "refills_remaining": 0, "last_fill_date": "2026-09-12", "next_eligible_date": None, "pharmacy": "Bayview Pharmacy",
                 "notes": "No refills left; a new prescription is needed."},
}

NURSE_LINE = "1-800-555-0142"
