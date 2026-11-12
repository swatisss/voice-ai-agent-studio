"""Synthetic business records behind the mock Northgate Health API (UK private medical insurance).

Spec: /demo-data/northgate-members.md, /api/mock-healthcare-api.md
Dates written T±n in the spec are relative to the day the process starts (or `reset()` is called).
Every person, number and address is fictional; phone numbers use the Ofcom drama range 07700 900xxx.
"""
from __future__ import annotations

import copy
import re
from datetime import date, timedelta
from typing import Any

BRAND = "Northgate Health"
MEMBER_PREFIX = "NGH"

# ---------------------------------------------------------------- products (/demo-data/northgate-members.md "Products")
PRODUCTS = {
    "complete": {"name": "Northgate Complete", "factor": 1.0,
                 "summary": "Diagnosis and treatment: consultations, tests, scans, surgery, cancer care, mental health and therapies."},
    "essentials": {"name": "Northgate Essentials", "factor": 0.70,
                   "summary": "Treatment and care once you have a diagnosis (from the NHS or a self-pay consultation); no outpatient diagnostics."},
}
OUTPATIENT_LIMITS = {"unlimited": 1.0, "1000": 0.88, "750": 0.84, "500": 0.80}  # Complete only; Essentials has no outpatient diagnostics
EXCESSES = {0: 1.0, 100: 0.94, 250: 0.87, 500: 0.78}
HOSPITAL_LISTS = {
    "essential": (0.85, "Essential list: about 200 partner hospitals outside central London"),
    "extended": (1.0, "Extended list: about 300 hospitals across the UK, outside central London"),
    "london_premium": (1.20, "London Premium list: every recognised hospital, including central London"),
}
ADD_ONS = {  # per person per month
    "dental_optical": (11.50, "Dental and optical: one check-up a year plus a £300 dental and £150 optical allowance"),
    "therapies_plus": (6.00, "Therapies Plus: unlimited physiotherapy, osteopathy and chiropractic sessions when clinically needed"),
    "travel_cover": (4.50, "Worldwide emergency medical cover for trips up to 30 days"),
}
AGE_BASE = [  # (max age, monthly base for Complete, extended list, unlimited outpatient, £0 excess)
    (17, 22.0), (24, 38.0), (29, 42.0), (34, 48.0), (39, 55.0), (44, 64.0), (49, 75.0), (54, 89.0), (59, 106.0), (64, 128.0), (69, 155.0), (200, 190.0),
]
REGION_FACTORS = [  # postcode area prefixes -> factor (first match wins)
    (("EC", "WC", "E", "N", "NW", "SE", "SW", "W"), 1.25, "London"),
    (("BN", "GU", "RH", "TN", "OX", "RG", "SL", "HP", "KT", "SM", "CR", "BR", "TW", "UB", "HA", "EN", "IG", "RM", "DA", "ME", "CT", "SO", "PO"), 1.10, "South East"),
    (("EH", "G", "AB", "DD", "KY", "FK", "PA", "IV", "NE", "SR", "DH", "TS", "CF", "SA", "NP", "LL", "BT"), 0.90, "Scotland, North East, Wales and Northern Ireland"),
]
SMOKER_LOADING = 1.10
MULTI_PERSON_DISCOUNT = {2: 0.05, 3: 0.10}  # couples 5%, three or more people 10%
QUOTE_VALID_DAYS = 14
PACKAGES = {  # the three starting packages every quote shows
    "essentials": {"label": "Essentials", "product": "essentials", "outpatient_limit": None, "excess": 250, "hospital_list": "essential"},
    "balanced": {"label": "Balanced", "product": "complete", "outpatient_limit": "1000", "excess": 100, "hospital_list": "extended"},
    "complete": {"label": "Complete", "product": "complete", "outpatient_limit": "unlimited", "excess": 0, "hospital_list": "extended"},
}
UNDERWRITING_METHODS = {
    "moratorium": "Moratorium: no medical questions now; conditions you had symptoms, treatment or advice for in the 5 years before cover starts are excluded until you have 2 clear years on cover.",
    "full_medical": "Full medical underwriting: you tell us your medical history now and we list any exclusions up front.",
    "switch": "Switch: you keep the underwriting terms of your current UK insurer if you have had at least 12 months of continuous cover with no break.",
}
SERIOUS_CONDITIONS = ("cancer", "heart", "stroke", "kidney failure", "multiple sclerosis", "hiv")
HAZARD_POINTS = 10

# ---------------------------------------------------------------- members (/demo-data/northgate-members.md "Members")
MEMBERS = {
    "NGH-410237": {"first_name": "Sarah", "last_name": "Mitchell", "dob": "1984-03-14", "plan": "Northgate Complete", "email": "sarah.mitchell@example.co.uk",
                   "mobile": "07700 900141", "address": "14 Larkfield Road, Leeds LS6 2AB"},
    "NGH-522918": {"first_name": "David", "last_name": "Okoro", "dob": "1977-09-02", "plan": "Northgate Essentials", "email": "david.okoro@example.co.uk",
                   "mobile": "07700 900142", "address": "3 Canal Street, Manchester M1 3HE"},
    "NGH-638405": {"first_name": "Emma", "last_name": "Clarke", "dob": "1991-06-21", "plan": "Northgate Complete", "email": "emma.clarke@example.co.uk",
                   "mobile": "07700 900143", "address": "27 Cotham Hill, Bristol BS6 6JY"},
    "NGH-714560": {"first_name": "Raj", "last_name": "Patel", "dob": "1966-11-30", "plan": "Northgate Complete", "email": "raj.patel@example.co.uk",
                   "mobile": "07700 900144", "address": "88 Fortis Green, London N2 9EY"},
    "NGH-805193": {"first_name": "Tom", "last_name": "Harris", "dob": "2000-01-08", "plan": "Northgate Essentials", "email": "tom.harris@example.co.uk",
                   "mobile": "07700 900145", "address": "5 Moseley Road, Birmingham B12 9AA"},
    "NGH-917362": {"first_name": "Lucy", "last_name": "Evans", "dob": "1959-05-17", "plan": "Northgate Cash Plan Level 3", "email": "lucy.evans@example.co.uk",
                   "mobile": "07700 900146", "address": "40 Pontcanna Street, Cardiff CF11 9HQ"},
}
PHONES = {"+447700900141": "NGH-410237", "+447700900142": "NGH-522918", "+447700900143": "NGH-638405"}
PREFERRED_CONTACT = {"NGH-410237": "email", "NGH-522918": "phone, after 6pm", "NGH-638405": "SMS"}

# ---------------------------------------------------------------- health claims and pre-authorisations
CLAIMS = {
    "CL-70231": {"member": "NGH-410237", "policy_id": "PMI-300101", "type": "health", "service": "Knee MRI scan", "provider": "Headingley Park Imaging",
                 "service_date": "2026-09-22", "billed": 650.0, "status": "paid", "plan_paid": 550.0, "member_responsibility": 100.0, "paid_date": "2026-10-03",
                 "notes": "Paid directly to the hospital under pre-authorisation PA-500812; your £100 excess applied.",
                 "timeline": [{"date": "2026-09-22", "event": "Invoice received from the hospital"}, {"date": "2026-10-03", "event": "Paid to the hospital"}],
                 "next_step": "Nothing to do. The hospital may ask you to pay the £100 excess."},
    "CL-70412": {"member": "NGH-522918", "policy_id": "PMI-300214", "type": "health", "service": "Consultation with an orthopaedic surgeon", "provider": "Mr Alan Price, Manchester",
                 "service_date": "2026-10-08", "billed": 280.0, "status": "paid", "plan_paid": 220.0, "member_responsibility": 60.0, "paid_date": "2026-10-20",
                 "notes": "The consultant charged £60 above our fee guidelines (a shortfall); he is not fee-assured.",
                 "timeline": [{"date": "2026-10-08", "event": "Invoice received"}, {"date": "2026-10-20", "event": "Paid £220 to the consultant"}],
                 "next_step": "The consultant may bill you the £60 shortfall."},
    "CL-70588": {"member": "NGH-638405", "policy_id": "PMI-300377", "type": "health", "service": "Physiotherapy, 4 sessions", "provider": "Clifton Physio Centre",
                 "service_date": "2026-10-20", "billed": 260.0, "status": "processing", "expected_decision_date_offset": 3,
                 "timeline": [{"date": "2026-10-28", "event": "Invoice received"}, {"date": "2026-11-02", "event": "In review"}],
                 "next_step": "We expect to pay the clinic within a few days."},
    "CL-70640": {"member": "NGH-714560", "policy_id": "PMI-300452", "type": "health", "service": "Lumbar spine injection", "provider": "St John's Wood Clinic, London",
                 "service_date": "2026-10-02", "billed": 2400.0, "status": "declined", "plan_paid": 0.0,
                 "denial_reason": "Lower back conditions are excluded on this policy (full medical underwriting exclusion)",
                 "timeline": [{"date": "2026-10-05", "event": "Invoice received"}, {"date": "2026-10-16", "event": "Declined: excluded condition"}],
                 "next_step": "If you disagree, our customer relations team can review the decision."},
}
PRE_AUTHS = {
    "PA-500812": {"member": "NGH-410237", "policy_id": "PMI-300101", "service": "Knee MRI scan", "condition": "knee pain", "status": "approved",
                  "decision_date": "2026-09-15", "valid_through": "2026-12-15", "consultant": "Mr James Holloway", "hospital": "Headingley Park Hospital",
                  "notes": "Covers the scan and one follow-up consultation."},
    "PA-500955": {"member": "NGH-638405", "policy_id": "PMI-300377", "service": "Shoulder arthroscopy", "condition": "shoulder pain", "status": "pending",
                  "expected_decision_date_offset": 2, "notes": "Waiting for the consultant's procedure code and fee estimate."},
    "PA-501020": {"member": "NGH-522918", "policy_id": "PMI-300214", "service": "Knee replacement", "condition": "knee osteoarthritis", "status": "approved",
                  "decision_date": "2026-10-25", "valid_through": "2027-01-25", "consultant": "Mr Alan Price", "hospital": "Didsbury Private Hospital",
                  "notes": "Covers surgery, the hospital stay and 6 physiotherapy sessions afterwards."},
}
PRE_AUTH_BASE = 502000

# conditions that never need a GP referral (Direct Access, /demo-data/northgate-members.md)
DIRECT_ACCESS = {
    "muscles_bones_joints": ("back pain", "neck pain", "knee pain", "shoulder pain", "hip pain", "sports injury", "joint pain", "muscle", "bone", "joint"),
    "mental_health": ("anxiety", "depression", "stress", "low mood", "mental health", "panic", "insomnia"),
    "cancer_symptoms": ("lump", "unexplained weight loss", "cancer", "blood in"),
    "skin": ("mole", "skin lesion"),
}
# condition keyword -> specialty
SPECIALTY_FOR = {
    "knee": "orthopaedics", "hip": "orthopaedics", "shoulder": "orthopaedics", "back": "orthopaedics", "neck": "orthopaedics", "joint": "orthopaedics", "sports": "orthopaedics",
    "anxiety": "psychiatry", "depression": "psychiatry", "stress": "psychiatry", "mental": "psychiatry",
    "skin": "dermatology", "mole": "dermatology", "rash": "dermatology", "eczema": "dermatology",
    "heart": "cardiology", "chest": "cardiology", "palpitations": "cardiology",
    "stomach": "gastroenterology", "bowel": "gastroenterology", "reflux": "gastroenterology",
    "lump": "oncology", "cancer": "oncology", "breast": "oncology",
    "ear": "ent", "nose": "ent", "throat": "ent", "sinus": "ent",
    "cataract": "ophthalmology", "eye": "ophthalmology",
}
SPECIALISTS = [  # recognised consultants (Finder); fee_assured = billed within our limits, so no shortfall
    {"id": "CN-101", "name": "Mr James Holloway", "specialty": "orthopaedics", "hospital": "Headingley Park Hospital", "area": "LS", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 6, "remote": False},
    {"id": "CN-102", "name": "Ms Priya Desai", "specialty": "orthopaedics", "hospital": "Roundhay Private Hospital", "area": "LS", "lists": ["extended", "london_premium"], "fee_assured": True, "next_available_days": 9, "remote": True},
    {"id": "CN-103", "name": "Mr Alan Price", "specialty": "orthopaedics", "hospital": "Didsbury Private Hospital", "area": "M", "lists": ["extended", "london_premium"], "fee_assured": False, "next_available_days": 4, "remote": False},
    {"id": "CN-104", "name": "Dr Fiona Grant", "specialty": "orthopaedics", "hospital": "Bath Abbey Clinic", "area": "BS", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 5, "remote": True},
    {"id": "CN-105", "name": "Mr Oliver Reed", "specialty": "orthopaedics", "hospital": "Clifton Downs Hospital", "area": "BS", "lists": ["extended", "london_premium"], "fee_assured": True, "next_available_days": 8, "remote": False},
    {"id": "CN-106", "name": "Mr Daniel Shaw", "specialty": "orthopaedics", "hospital": "St John's Wood Hospital", "area": "NW", "lists": ["london_premium"], "fee_assured": True, "next_available_days": 3, "remote": False},
    {"id": "CN-201", "name": "Dr Helen Moss", "specialty": "dermatology", "hospital": "Headingley Park Hospital", "area": "LS", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 7, "remote": True},
    {"id": "CN-202", "name": "Dr Kwame Asante", "specialty": "dermatology", "hospital": "Harley Court Clinic", "area": "W", "lists": ["london_premium"], "fee_assured": True, "next_available_days": 4, "remote": True},
    {"id": "CN-301", "name": "Dr Laura Bennett", "specialty": "psychiatry", "hospital": "Redland House Hospital", "area": "BS", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 5, "remote": True},
    {"id": "CN-302", "name": "Dr Samir Haddad", "specialty": "psychiatry", "hospital": "Northgate Mind Clinic, Manchester", "area": "M", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 3, "remote": True},
    {"id": "CN-401", "name": "Dr Rachel Kim", "specialty": "cardiology", "hospital": "Roundhay Private Hospital", "area": "LS", "lists": ["extended", "london_premium"], "fee_assured": True, "next_available_days": 10, "remote": False},
    {"id": "CN-501", "name": "Mr Thomas Wright", "specialty": "gastroenterology", "hospital": "Didsbury Private Hospital", "area": "M", "lists": ["extended", "london_premium"], "fee_assured": True, "next_available_days": 8, "remote": True},
    {"id": "CN-601", "name": "Dr Anika Sharma", "specialty": "oncology", "hospital": "Harley Court Clinic", "area": "W", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 2, "remote": False},
    {"id": "CN-602", "name": "Dr Mark Ellis", "specialty": "oncology", "hospital": "Headingley Park Hospital", "area": "LS", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 2, "remote": False},
    {"id": "CN-701", "name": "Ms Claire Douglas", "specialty": "ent", "hospital": "Clifton Downs Hospital", "area": "BS", "lists": ["extended", "london_premium"], "fee_assured": True, "next_available_days": 9, "remote": True},
    {"id": "CN-801", "name": "Mr Peter Lang", "specialty": "ophthalmology", "hospital": "Didsbury Private Hospital", "area": "M", "lists": ["essential", "extended", "london_premium"], "fee_assured": True, "next_available_days": 12, "remote": False},
]

# policy -> exclusions (full medical underwriting) or moratorium conditions
EXCLUSIONS = {"PMI-300452": ["lower back conditions", "back pain"]}
MORATORIUM_CONDITIONS = {"PMI-300377": ["migraine"]}  # Emma: symptoms in the 5 years before cover
OUTPATIENT_USED = {"PMI-300377": 640.0}  # this policy year, against a £1,000 outpatient limit
EXCESS_USED = {"PMI-300101": 100.0}  # the excess applies once per person per policy year

# ---------------------------------------------------------------- cash plan (/demo-data/northgate-members.md "Cash plan")
CASH_PLAN_LEVELS = {  # benefit -> yearly limit per level; percent refunded
    "Level 1": {"dental": 200, "optical": 60, "therapies": 100, "consultations": 150, "hospital_nights": 400},
    "Level 2": {"dental": 300, "optical": 120, "therapies": 200, "consultations": 250, "hospital_nights": 600},
    "Level 3": {"dental": 400, "optical": 200, "therapies": 300, "consultations": 350, "hospital_nights": 800},
}
CASH_PLAN_REFUND_PERCENT = 100
CASH_PLAN_CLAIMS = {
    "CC-81204": {"member": "NGH-917362", "policy_id": "CSH-400118", "benefit": "dental", "provider": "Pontcanna Dental", "treatment_date": "2026-10-14",
                 "amount_claimed": 145.0, "status": "paid", "amount_paid": 145.0, "paid_date": "2026-10-19", "notes": "Paid to your bank account."},
    "CC-81377": {"member": "NGH-917362", "policy_id": "CSH-400118", "benefit": "optical", "provider": "Cardiff Bay Opticians", "treatment_date": "2026-11-03",
                 "amount_claimed": 220.0, "status": "processing", "expected_decision_date_offset": 2,
                 "notes": "Your optical limit is £200 a year, so we can pay up to £200 of this claim."},
    "CC-81402": {"member": "NGH-638405", "policy_id": "CSH-400204", "benefit": "therapies", "provider": "Clifton Physio Centre", "treatment_date": "2026-11-01",
                 "amount_claimed": 65.0, "status": "more information needed",
                 "notes": "The receipt does not show the patient's name. Upload a receipt that shows the patient's name, the provider, the date and the cost."},
}
CASH_PLAN_USAGE = {"NGH-917362": {"dental": 145, "optical": 0}, "NGH-638405": {"therapies": 0}}

# ---------------------------------------------------------------- documents
DOCUMENT_TYPES = {
    "membership_certificate": ("Membership certificate (who is covered, your options and any exclusions)", ("health",)),
    "policy_guide": ("Policy guide (terms and conditions)", ("health", "cash_plan")),
    "membership_card": ("Digital membership card", ("health", "cash_plan")),
    "premium_statement": ("Premium statement for the year", ("health", "cash_plan")),
    "table_of_benefits": ("Cash plan table of benefits", ("cash_plan",)),
}
DELIVERY = {"email": "within 15 minutes", "sms": "a link by text within 5 minutes", "post": "5 to 7 working days"}
SECURE_LINK_PURPOSES = {
    "change_bank_details": "Change the bank account for your Direct Debit",
    "direct_debit_setup": "Set up your Direct Debit",
    "make_payment": "Pay a missed premium by debit card",
}

# ---------------------------------------------------------------- Digital GP (6am-10pm weekdays, 8am-10pm weekends)
GP_TYPES = {"gp": "GP", "nurse": "advanced nurse practitioner"}
GP_FORMATS = ("video", "phone")

# ---------------------------------------------------------------- complaints and other contacts (fictional numbers)
LINES = {
    "member_services": ("0345 600 0101", "Monday to Friday 8am to 8pm, Saturday 8am to 4pm"),
    "sales": ("0800 600 0102", "Monday to Friday 8am to 8pm, Saturday 9am to 1pm"),
    "claims": ("0345 600 0103", "Monday to Friday 8am to 8pm, Saturday 8am to 4pm"),
    "cash_plan": ("0345 600 0104", "Monday to Friday 8am to 6pm, Saturday 8am to 1pm"),
    "nurse_line": ("0345 600 0105", "24 hours a day, 7 days a week"),
}

# ---------------------------------------------------------------- mutable, date-relative state
POLICIES: dict[str, dict[str, Any]] = {}
PAYMENTS: dict[str, dict[str, Any]] = {}
GP_SLOTS: list[dict[str, Any]] = []
GP_BOOKINGS: list[dict[str, Any]] = []
DOCUMENT_REQUESTS: list[dict[str, Any]] = []
SECURE_LINKS: list[dict[str, Any]] = []
CONTACT_CHANGES: list[dict[str, Any]] = []
QUOTES: dict[str, dict[str, Any]] = {}
UNDERWRITING: dict[str, dict[str, Any]] = {}
APPLICATIONS: dict[str, dict[str, Any]] = {}
NEW_IDS: dict[str, list[str]] = {"pre_auth": [], "member": [], "claim": []}
_counters = {"doc": 0, "link": 0, "gp": 0, "quote": 0, "uw": 0, "policy": 0, "member": 0, "pre_auth": 0, "retry": 0, "change": 0}

_BASE_MEMBERS = copy.deepcopy(MEMBERS)


def today() -> date:
    return date.today()


def rel(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


def reset() -> None:
    """Rebuild the date-relative and mutable records (process start, tests, `seed --reset`)."""
    def pol(member, kind, product, start, monthly, *, excess=None, outpatient=None, hospital_list=None, underwriting=None,  # noqa: ANN001
            insured=None, add_ons=None, level=None, status="active"):
        out = {"member": member, "type": kind, "product": product, "status": status, "start_date": rel(start),
               "renewal_date": rel(start + 365 if start + 365 > 0 else start + 730), "monthly_premium": monthly, "payment_method": "Direct Debit",
               "insured_persons": insured or [f"{MEMBERS[member]['first_name']} {MEMBERS[member]['last_name']}"]}
        if kind == "health":
            out.update(excess=excess, outpatient_limit=outpatient, hospital_list=hospital_list, underwriting=underwriting, add_ons=add_ons or [])
        else:
            out.update(level=level)
        return out

    MEMBERS.clear()
    MEMBERS.update(copy.deepcopy(_BASE_MEMBERS))
    POLICIES.clear()
    POLICIES.update({
        "PMI-300101": pol("NGH-410237", "health", "Northgate Complete", -320, 187.40, excess=100, outpatient="unlimited", hospital_list="extended",
                          underwriting="moratorium", insured=["Sarah Mitchell", "Ben Mitchell", "Isla Mitchell"], add_ons=["dental_optical"]),
        "PMI-300214": pol("NGH-522918", "health", "Northgate Essentials", -400, 61.20, excess=250, outpatient=None, hospital_list="essential",
                          underwriting="full_medical"),
        "PMI-300377": pol("NGH-638405", "health", "Northgate Complete", -150, 52.80, excess=100, outpatient="1000", hospital_list="extended",
                          underwriting="moratorium", add_ons=["therapies_plus"]),
        "PMI-300452": pol("NGH-714560", "health", "Northgate Complete", -500, 168.90, excess=0, outpatient="unlimited", hospital_list="london_premium",
                          underwriting="full_medical"),
        "PMI-300519": pol("NGH-805193", "health", "Northgate Essentials", -10, 29.60, excess=250, outpatient=None, hospital_list="essential",
                          underwriting="moratorium"),
        "CSH-400118": pol("NGH-917362", "cash_plan", "Northgate Cash Plan Level 3", -220, 23.30, level="Level 3"),
        "CSH-400204": pol("NGH-638405", "cash_plan", "Northgate Cash Plan Level 2", -90, 13.50, level="Level 2"),
    })
    POLICIES["PMI-300519"]["cooling_off_ends"] = rel(11)  # 21 days from the start date
    POLICIES["PMI-300214"]["status"] = "payment_missed"
    PAYMENTS.clear()
    for pid, p in POLICIES.items():
        PAYMENTS[pid] = {"collection_day": 1, "status": "up_to_date", "next_collection_date": _next_first(), "amount": p["monthly_premium"],
                         "bank_account": "account ending 4821", "history": [{"date": _first_of_month(-k), "amount": p["monthly_premium"], "status": "collected"} for k in (1, 2, 3)],
                         "missed_amount": 0.0, "reinstate_by": None}
    PAYMENTS["PMI-300214"].update(status="missed", missed_amount=61.20, reinstate_by=rel(19), bank_account="account ending 0937",
                                  history=[{"date": _first_of_month(0), "amount": 61.20, "status": "failed: insufficient funds"},
                                           {"date": _first_of_month(-1), "amount": 61.20, "status": "collected"}])
    PAYMENTS["PMI-300519"].update(history=[], next_collection_date=_next_first())
    GP_SLOTS.clear()
    for day in range(1, 4):
        for hour, kind, fmt in ((9, "gp", "video"), (12, "nurse", "phone"), (18, "gp", "phone"), (20, "gp", "video")):
            GP_SLOTS.append({"slot_id": f"GP-{day}{hour:02d}", "date": rel(day), "time": f"{hour:02d}:00", "clinician": GP_TYPES[kind], "type": kind,
                             "format": fmt, "booked": False})
    for collection in (GP_BOOKINGS, DOCUMENT_REQUESTS, SECURE_LINKS, CONTACT_CHANGES):
        collection.clear()
    for d in (QUOTES, UNDERWRITING, APPLICATIONS):
        d.clear()
    for pid in NEW_IDS["pre_auth"]:
        PRE_AUTHS.pop(pid, None)
    for k in NEW_IDS:
        NEW_IDS[k].clear()
    for k in _counters:
        _counters[k] = 0


def _first_of_month(months_offset: int) -> str:
    t = today().replace(day=1)
    y, m = t.year, t.month + months_offset
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return date(y, m, 1).isoformat()


def _next_first() -> str:
    return _first_of_month(1)


def next_id(kind: str) -> int:
    _counters[kind] += 1
    return _counters[kind]


def region_area(postcode: str) -> str:
    """The postcode area: the leading letters of the outward code (SW1A 1AA -> SW, LS6 2AB -> LS)."""
    return re.match(r"[A-Z]*", postcode.strip().upper().split(" ")[0]).group(0)


def region_of(postcode: str) -> tuple[float, str]:
    area = region_area(postcode)
    for prefixes, factor, name in REGION_FACTORS:
        if area in prefixes:
            return factor, name
    return 1.0, "Rest of England"


def age_on(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def base_for_age(age: int) -> float:
    return next(price for top, price in AGE_BASE if age <= top)


def snapshot() -> dict[str, Any]:  # for tests
    return copy.deepcopy({"policies": POLICIES, "payments": PAYMENTS, "applications": APPLICATIONS})


reset()
