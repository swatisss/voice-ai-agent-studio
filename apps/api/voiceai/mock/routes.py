"""Mock Northgate Health business API (member services, claims and pre-authorisation, sales), called by agents as tools.

Spec: /api/mock-healthcare-api.md, /demo-data/northgate-members.md
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from voiceai.mock import data

router = APIRouter(prefix="/mock", tags=["mock"])

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})


# ---------------------------------------------------------------- normalization
def norm_member(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    s = s.removeprefix(data.MEMBER_PREFIX)
    return f"{data.MEMBER_PREFIX}-{s}" if s.isdigit() else None


def norm_id(raw: str) -> str:
    """cl70231 -> CL-70231, pmi300101 -> PMI-300101, PA-500812 stays."""
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    m = re.fullmatch(r"([A-Z]+)(\d+)", s)
    return f"{m.group(1)}-{m.group(2)}" if m else raw.strip().upper()


def norm_key(raw: str) -> str:
    return re.sub(r"[\s\-]+", "_", raw.strip().lower())


def parse_date(raw: str) -> date | None:
    """ISO, UK numeric (14/03/1984) and spoken dates (14 March 1984, March 14th 1984)."""
    s = raw.strip().lower().replace(",", " ")
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    s = re.sub(r"\bof\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    words = s.split(" ")
    try:
        if len(words) == 3 and words[0] in MONTHS:  # march 14 1984
            return date(int(words[2]), MONTHS[words[0]], int(words[1]))
        if len(words) == 3 and words[1] in MONTHS:  # 14 march 1984
            return date(int(words[2]), MONTHS[words[1]], int(words[0]))
    except ValueError:
        return None
    return None


parse_dob = parse_date  # backwards-compatible name


def err(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail, **extra}, status_code=status)


def unverified() -> JSONResponse:
    return err(401, "member_not_verified", "Verify the member first")


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"mobile ending {digits[-3:]}" if digits else "the mobile on file"


def money(x: float) -> float:
    return round(x + 1e-9, 2)


def _decision_date(rec: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in rec.items() if k not in ("member", "expected_decision_date_offset")}
    if "expected_decision_date_offset" in rec:
        out["expected_decision_date"] = data.rel(rec["expected_decision_date_offset"])
    return out


def _owned_policy(policy_id: str, member: str) -> tuple[str, dict[str, Any] | None]:
    pid = norm_id(policy_id)
    p = data.POLICIES.get(pid)
    return pid, (p if p and p["member"] == member else None)


def _matches(text: str, words: list[str] | tuple[str, ...]) -> bool:
    t = text.lower()
    return any(w in t for w in words)


# ================================================================ identity
class VerifyBody(BaseModel):
    member_id: str | None = None
    date_of_birth: str


class IdentifyBody(BaseModel):
    phone: str


def norm_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("07") and len(digits) == 11:  # UK mobile written nationally
        digits = "44" + digits[1:]
    return f"+{digits}" if digits else ""


@router.post("/healthcare/identify")
async def identify(body: IdentifyBody) -> dict[str, Any]:
    """MOCK-15: who a registered phone number belongs to - the first name and nothing more."""
    ref = data.PHONES.get(norm_phone(body.phone))
    if not ref:
        return {"matched": False}
    return {"matched": True, "member_ref": ref, "first_name": data.MEMBERS[ref]["first_name"]}


@router.post("/healthcare/verify", response_model=None)
async def verify(body: VerifyBody, x_identified_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if body.member_id:
        ref = norm_member(body.member_id)
    elif x_identified_ref:  # MOCK-16: an identified caller verifies with the date of birth alone
        ref = x_identified_ref
    else:
        return err(422, "member_id_required", "Give the membership number, or call from the number on the member's record")
    member = data.MEMBERS.get(ref or "")
    dob = parse_date(body.date_of_birth)
    if not member or not dob or dob.isoformat() != member["dob"]:
        return {"verified": False, "reason": "Membership number and date of birth do not match our records."}
    return {"verified": True, "member_ref": ref, "first_name": member["first_name"], "plan_name": member["plan"]}


@router.get("/healthcare/members/me", response_model=None)
async def member_profile(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    """MOCK-17: the verified member's profile, used to personalise the call; never stored by the platform."""
    member = data.MEMBERS.get(x_member_ref or "")
    if not member:
        return unverified()
    policies = [{"policy_id": pid, "product": p["product"], "status": p["status"]}
                for pid, p in data.POLICIES.items() if p["member"] == x_member_ref]
    open_claims = [{"claim_id": cid, "status": c["status"]}
                   for cid, c in data.CLAIMS.items() if c["member"] == x_member_ref and c["status"] != "paid"]
    return {"first_name": member["first_name"], "plan_name": member["plan"], "policies": policies, "open_claims": open_claims,
            "preferred_contact": data.PREFERRED_CONTACT.get(x_member_ref or "")}


# ================================================================ policies, payments, details, documents (Customer Care)
def _cover_summary(p: dict[str, Any]) -> dict[str, Any]:
    if p["type"] == "cash_plan":
        return {"level": p["level"], "yearly_limits": data.CASH_PLAN_LEVELS[p["level"]]}
    return {
        "excess": p["excess"], "outpatient_limit": p["outpatient_limit"] or "not included (Essentials covers treatment after diagnosis)",
        "hospital_list": data.HOSPITAL_LISTS[p["hospital_list"]][1], "underwriting": p["underwriting"],
        "add_ons": [data.ADD_ONS[a][1] for a in p["add_ons"]],
    }


@router.get("/insurance/policies", response_model=None)
async def policies(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    rows = [{"policy_id": pid, "type": p["type"], "product": p["product"], "status": p["status"], "start_date": p["start_date"], "renewal_date": p["renewal_date"]}
            for pid, p in data.POLICIES.items() if p["member"] == x_member_ref]
    return {"policies": sorted(rows, key=lambda r: (r["type"] != "health", r["policy_id"]))}


@router.get("/insurance/policies/{policy_id}", response_model=None)
async def policy(policy_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    pay = data.PAYMENTS[pid]
    out = {"policy_id": pid, "type": p["type"], "product": p["product"], "status": p["status"], "start_date": p["start_date"],
           "renewal_date": p["renewal_date"], "monthly_premium": p["monthly_premium"], "payment_status": pay["status"],
           "next_collection_date": pay["next_collection_date"], "insured_persons": p["insured_persons"], "cover": _cover_summary(p),
           "cooling_off_ends": p.get("cooling_off_ends"), "exclusions": data.EXCLUSIONS.get(pid, [])[:1]}
    return out


@router.get("/insurance/policies/{policy_id}/payments", response_model=None)
async def payments(policy_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    pay = data.PAYMENTS[pid]
    out = {"policy_id": pid, "payment_method": "Direct Debit", "status": pay["status"], "monthly_amount": pay["amount"],
           "collection_day": pay["collection_day"], "next_collection_date": pay["next_collection_date"], "bank_account": pay["bank_account"],
           "recent_payments": pay["history"][:3], "missed_amount": pay["missed_amount"], "reinstate_by": pay["reinstate_by"]}
    if pay["status"] == "missed":
        out["what_happens"] = ("Cover is suspended while a payment is missed. Pay the missed amount by the reinstate_by date "
                               "(retry the Direct Debit or pay by card through a secure link) and cover continues with no gap; after that date the policy is cancelled.")
    elif pay.get("retry"):
        out["retry"] = pay["retry"]
    return out


class RetryBody(BaseModel):
    collect_on: str | None = None


@router.post("/insurance/policies/{policy_id}/payments/retry", response_model=None)
async def retry_payment(policy_id: str, body: RetryBody | None = None, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    pay = data.PAYMENTS[pid]
    if pay["status"] != "missed":
        return err(409, "nothing_missed", "There is no missed payment on this policy")
    when = parse_date(body.collect_on) if body and body.collect_on else data.today() + timedelta(days=3)
    if when is None or not data.today() + timedelta(days=3) <= when <= date.fromisoformat(pay["reinstate_by"]):
        return err(422, "invalid_collection_date", f"Choose a date between {data.rel(3)} and {pay['reinstate_by']} (a Direct Debit needs 3 working days' notice)")
    ref = f"RT-{data.next_id('retry'):05d}"
    pay.update(status="retry_scheduled", retry={"reference": ref, "collect_on": when.isoformat(), "amount": pay["missed_amount"]})
    return {"reference": ref, "policy_id": pid, "amount": pay["missed_amount"], "collect_on": when.isoformat(), "bank_account": pay["bank_account"],
            "next_step": "Make sure the money is in the account on that day. Cover is restored once the payment is collected, with no gap."}


class CollectionDayBody(BaseModel):
    day: int


@router.post("/insurance/policies/{policy_id}/payments/collection-day", response_model=None)
async def collection_day(policy_id: str, body: CollectionDayBody, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    if not 1 <= body.day <= 28:
        return err(422, "invalid_day", "Choose a collection day from the 1st to the 28th of the month")
    pay = data.PAYMENTS[pid]
    if pay["status"] == "missed":
        return err(409, "payment_missed", "Pay the missed amount before changing the collection day")
    pay["collection_day"] = body.day
    first = date.fromisoformat(data._next_first())
    nxt = first.replace(day=body.day)
    pay["next_collection_date"] = nxt.isoformat()
    return {"policy_id": pid, "collection_day": body.day, "next_collection_date": nxt.isoformat(), "amount": pay["amount"],
            "note": "The change takes effect from next month's collection."}


class ContactBody(BaseModel):
    email: str | None = None
    mobile: str | None = None
    address: str | None = None


@router.post("/insurance/members/me/contact", response_model=None)
async def update_contact(body: ContactBody, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    changes = {k: v.strip() for k, v in body.model_dump().items() if v and v.strip()}
    if not changes:
        return err(422, "nothing_to_change", "Give a new email address, mobile number or postal address")
    if "email" in changes and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", changes["email"]):
        return err(422, "invalid_email", "That does not look like an email address")
    if "mobile" in changes and not re.fullmatch(r"(\+44|0)7\d{9}", re.sub(r"[\s\-()]", "", changes["mobile"])):
        return err(422, "invalid_mobile", "Give a UK mobile number starting 07")
    if "address" in changes and not re.search(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", changes["address"].upper()):
        return err(422, "invalid_address", "The address needs a full UK postcode")
    member = data.MEMBERS[x_member_ref]
    member.update(changes)
    ref = f"CH-{data.next_id('change'):05d}"
    data.CONTACT_CHANGES.append({"reference": ref, "member": x_member_ref, "changed": sorted(changes)})
    confirm = mask_email(member["email"]) if "email" in changes else mask_phone(member["mobile"])
    return {"reference": ref, "changed": sorted(changes), "confirmation_sent_to": confirm,
            "note": "Bank details cannot be changed by phone; use a secure link."}


class SecureLinkBody(BaseModel):
    purpose: str
    channel: str = "sms"
    policy_id: str | None = None


@router.post("/insurance/secure-links", response_model=None)
async def secure_link(body: SecureLinkBody, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    purpose, channel = norm_key(body.purpose), body.channel.strip().lower()
    if purpose not in data.SECURE_LINK_PURPOSES:
        return err(422, "unknown_purpose", "Unknown purpose", purposes=sorted(data.SECURE_LINK_PURPOSES))
    if channel not in ("sms", "email"):
        return err(422, "invalid_channel", "Send the link by sms or email")
    member = data.MEMBERS[x_member_ref]
    lid = f"SL-{data.next_id('link'):05d}"
    out = {"link_id": lid, "purpose": data.SECURE_LINK_PURPOSES[purpose], "channel": channel,
           "sent_to": mask_email(member["email"]) if channel == "email" else mask_phone(member["mobile"]), "expires_in_hours": 24}
    data.SECURE_LINKS.append({**out, "member": x_member_ref, "policy_id": body.policy_id})
    return out


@router.get("/insurance/documents", response_model=None)
async def documents(policy_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    docs = [{"document_type": k, "title": title, "delivery_options": list(data.DELIVERY)}
            for k, (title, types) in data.DOCUMENT_TYPES.items() if p["type"] in types]
    return {"policy_id": pid, "documents": docs}


class DocumentRequest(BaseModel):
    policy_id: str
    document_type: str
    delivery: str


@router.post("/insurance/documents/request", response_model=None)
async def request_document(body: DocumentRequest, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(body.policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    dtype, delivery = norm_key(body.document_type), body.delivery.strip().lower()
    spec = data.DOCUMENT_TYPES.get(dtype)
    if spec is None or p["type"] not in spec[1]:
        return err(409, "document_not_available", f"'{body.document_type}' is not available for this policy",
                   available=[k for k, (_, t) in data.DOCUMENT_TYPES.items() if p["type"] in t])
    if delivery not in data.DELIVERY:
        return err(409, "delivery_not_available", f"Delivery by {delivery} is not available", options=list(data.DELIVERY))
    member = data.MEMBERS[x_member_ref]
    rid = f"DOC-{data.next_id('doc'):05d}"
    sent_to = {"email": mask_email(member["email"]), "sms": mask_phone(member["mobile"]), "post": "the address on file"}[delivery]
    out = {"request_id": rid, "document_type": dtype, "title": spec[0], "delivery": delivery, "eta": data.DELIVERY[delivery],
           "status": "scheduled" if delivery == "post" else "queued", "sent_to": sent_to}
    data.DOCUMENT_REQUESTS.append({**out, "member": x_member_ref, "policy_id": pid})
    return out


# ================================================================ Digital GP
@router.get("/healthcare/gp/slots", response_model=None)
async def gp_slots(type: str = "gp", format: str | None = None, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:  # noqa: A002
    if x_member_ref not in data.MEMBERS:
        return unverified()
    kind = norm_key(type)
    kind = {"doctor": "gp", "nurse_practitioner": "nurse", "advanced_nurse_practitioner": "nurse"}.get(kind, kind)
    if kind not in data.GP_TYPES:
        return err(422, "invalid_type", "Choose gp or nurse")
    if not any(p["member"] == x_member_ref and p["type"] == "health" for p in data.POLICIES.values()):
        return err(409, "not_covered", "Digital GP appointments come with health insurance; this member has a cash plan only")
    slots = [s for s in data.GP_SLOTS if not s["booked"] and s["type"] == kind and (not format or s["format"] == format.strip().lower())]
    return {"clinician": data.GP_TYPES[kind], "hours": "6am to 10pm on weekdays, 8am to 10pm at weekends and on bank holidays",
            "slots": [{k: s[k] for k in ("slot_id", "date", "time", "format")} for s in slots[:4]]}


class GpBooking(BaseModel):
    slot_id: str
    reason: str
    patient_name: str | None = None


@router.post("/healthcare/gp/appointments", response_model=None)
async def book_gp(body: GpBooking, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    slot = next((s for s in data.GP_SLOTS if s["slot_id"] == norm_id(body.slot_id) or s["slot_id"] == body.slot_id.strip().upper()), None)
    if slot is None:
        return err(404, "slot_not_found", "No appointment with that reference")
    if slot["booked"]:
        return err(409, "slot_taken", "That appointment has just been taken; offer another")
    covered = {n for p in data.POLICIES.values() if p["member"] == x_member_ref and p["type"] == "health" for n in p["insured_persons"]}
    member = data.MEMBERS[x_member_ref]
    patient = (body.patient_name or f"{member['first_name']} {member['last_name']}").strip()
    match = next((n for n in sorted(covered) if n.lower() == patient.lower() or n.lower().startswith(patient.lower() + " ")), None)
    if match is None:
        return err(409, "patient_not_covered", "That person is not covered on this member's health policy", covered=sorted(covered))
    patient = match
    slot["booked"] = True
    bid = f"GPB-{data.next_id('gp'):05d}"
    booking = {"booking_id": bid, "date": slot["date"], "time": slot["time"], "clinician": slot["clinician"], "format": slot["format"],
               "patient": patient, "reason": body.reason.strip()[:200],
               "how_to_join": "A text with a link arrives 15 minutes before a video appointment; for a phone appointment the clinician calls your mobile."}
    data.GP_BOOKINGS.append({**booking, "member": x_member_ref})
    return booking


# ================================================================ cash plan
@router.get("/insurance/policies/{policy_id}/cash-benefits", response_model=None)
async def cash_benefits(policy_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    if p["type"] != "cash_plan":
        return err(409, "not_a_cash_plan", "This is a health insurance policy, not a cash plan")
    used = data.CASH_PLAN_USAGE.get(x_member_ref, {})
    benefits = [{"benefit": b, "yearly_limit": lim, "used": used.get(b, 0), "remaining": max(lim - used.get(b, 0), 0)}
                for b, lim in data.CASH_PLAN_LEVELS[p["level"]].items()]
    return {"policy_id": pid, "level": p["level"], "refund_percent": data.CASH_PLAN_REFUND_PERCENT, "benefits": benefits,
            "how_to_claim": "Claim online within 6 months of treatment with a receipt showing the patient's name, the provider, the date and the cost. "
                            "Claims are usually paid to your bank account within 5 working days."}


@router.get("/insurance/cash-plan/claims", response_model=None)
async def cash_claims(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    rows = [{"claim_id": cid, "benefit": c["benefit"], "provider": c["provider"], "treatment_date": c["treatment_date"], "status": c["status"]}
            for cid, c in data.CASH_PLAN_CLAIMS.items() if c["member"] == x_member_ref]
    return {"claims": sorted(rows, key=lambda r: r["treatment_date"], reverse=True)}


@router.get("/insurance/cash-plan/claims/{claim_id}", response_model=None)
async def cash_claim(claim_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    cid = norm_id(claim_id)
    c = data.CASH_PLAN_CLAIMS.get(cid)
    if not c or c["member"] != x_member_ref:
        return err(404, "claim_not_found", "No cash plan claim with that number for this member")
    out = {"claim_id": cid, **_decision_date(c)}
    for k in ("amount_paid", "paid_date", "expected_decision_date", "notes"):
        out.setdefault(k, None)
    return out


# ================================================================ health claims, cover checks, specialists, pre-authorisation
@router.get("/healthcare/claims", response_model=None)
async def member_claims(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    claims = [{"claim_id": cid, "service": c["service"], "service_date": c["service_date"], "status": c["status"]}
              for cid, c in data.CLAIMS.items() if c["member"] == x_member_ref]
    return {"claims": sorted(claims, key=lambda c: c["service_date"], reverse=True)}


@router.get("/healthcare/claims/{claim_id}", response_model=None)
async def claim(claim_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    cid = norm_id(claim_id)
    c = data.CLAIMS.get(cid)
    if not c or c["member"] != x_member_ref:
        return err(404, "claim_not_found", "No claim with that number for this member")
    out = {"claim_id": cid, **_decision_date(c)}
    for k in ("plan_paid", "member_responsibility", "paid_date", "denial_reason", "expected_decision_date", "notes"):
        out.setdefault(k, None)
    return out


@router.get("/healthcare/prior-auths/{auth_id}", response_model=None)
async def prior_auth(auth_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    aid = norm_id(auth_id)
    a = data.PRE_AUTHS.get(aid)
    if not a or a["member"] != x_member_ref:
        return err(404, "authorisation_not_found", "No pre-authorisation with that code for this member")
    out = {"auth_id": aid, **_decision_date(a)}
    for k in ("decision_date", "valid_through", "expected_decision_date", "consultant", "hospital", "notes"):
        out.setdefault(k, None)
    return out


def _specialty(condition: str) -> str | None:
    t = condition.lower()
    return next((s for k, s in data.SPECIALTY_FOR.items() if k in t), None)


def _direct_access(condition: str) -> str | None:
    t = condition.lower()
    return next((cat for cat, words in data.DIRECT_ACCESS.items() if any(w in t for w in words)), None)


DIAGNOSTIC_WORDS = ("consultation", "scan", "mri", "ct", "x-ray", "xray", "test", "diagnos", "ultrasound", "endoscopy", "appointment")
SURGERY_WORDS = ("surgery", "operation", "replacement", "arthroscopy", "removal", "procedure", "injection")


def _eligibility(pid: str, p: dict[str, Any], condition: str, treatment: str) -> dict[str, Any]:
    out: dict[str, Any] = {"policy_id": pid, "condition": condition, "treatment": treatment, "covered": True, "reason": "",
                           "direct_access_category": _direct_access(condition), "specialty": _specialty(condition),
                           "excess": p["excess"], "excess_remaining": max((p["excess"] or 0) - data.EXCESS_USED.get(pid, 0.0), 0),
                           "outpatient_limit": p["outpatient_limit"], "outpatient_remaining": None, "hospital_list": p["hospital_list"],
                           "forms_needed": []}
    out["referral_needed"] = out["direct_access_category"] is None
    if p["outpatient_limit"] not in (None, "unlimited"):
        out["outpatient_remaining"] = max(int(p["outpatient_limit"]) - data.OUTPATIENT_USED.get(pid, 0.0), 0)
    if p["status"] == "payment_missed":
        out.update(covered=False, reason="Cover is suspended because a monthly payment was missed; it restarts once the missed amount is paid.")
    elif _matches(condition, data.EXCLUSIONS.get(pid, [])):
        out.update(covered=False, reason="This condition is excluded on the membership certificate (full medical underwriting).")
    elif _matches(condition, data.MORATORIUM_CONDITIONS.get(pid, [])):
        out.update(covered=False, reason="Moratorium: symptoms of this condition in the 5 years before cover started; it is excluded until 2 clear years on cover.")
    elif p["product"] == "Northgate Essentials" and _matches(treatment, DIAGNOSTIC_WORDS) and not _matches(treatment, SURGERY_WORDS):
        out.update(covered=False, reason="Northgate Essentials covers treatment once you have a diagnosis; outpatient consultations, tests and scans for diagnosis are not included.")
    if p["underwriting"] == "moratorium" and out["covered"]:
        out["forms_needed"].append("pre-treatment form (moratorium): confirms the condition is new")
    if out["covered"] and out["outpatient_remaining"] is not None and _matches(treatment, DIAGNOSTIC_WORDS):
        out["note"] = f"Outpatient costs count towards the £{p['outpatient_limit']} yearly limit; £{out['outpatient_remaining']:.0f} is left."
    out["next_step"] = ("Not covered: explain the reason and offer customer relations if the member disagrees." if not out["covered"] else
                        "Covered: no GP referral is needed (Direct Access); suggest specialists and issue a pre-authorisation." if not out["referral_needed"] else
                        "Covered once a GP has seen the member: ask for an open referral (the type of specialist, not a named doctor), then suggest specialists and issue a pre-authorisation.")
    return out


@router.get("/insurance/policies/{policy_id}/eligibility", response_model=None)
async def eligibility(policy_id: str, condition: str, treatment: str = "consultation",
                      x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    if p["type"] != "health":
        return err(409, "not_applicable", "A cash plan pays money back after treatment; it does not pre-authorise treatment")
    return _eligibility(pid, p, condition.strip(), treatment.strip())


@router.get("/healthcare/specialists", response_model=None)
async def specialists(specialty: str = "", condition: str = "", postcode: str = "", policy_id: str | None = None,
                      x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    spec = norm_key(specialty) if specialty else (_specialty(condition) or "")
    spec = {"orthopaedic": "orthopaedics", "orthopedics": "orthopaedics", "psychiatrist": "psychiatry", "mental_health": "psychiatry",
            "skin": "dermatology", "dermatologist": "dermatology", "cardiologist": "cardiology", "ear_nose_and_throat": "ent"}.get(spec, spec)
    if not spec:
        return err(422, "specialty_required", "Say the type of specialist (for example orthopaedics) or the condition")
    hospital_list = None
    if policy_id and x_member_ref in data.MEMBERS:
        _, p = _owned_policy(policy_id, x_member_ref)
        hospital_list = p["hospital_list"] if p and p["type"] == "health" else None
    area = data.region_area(postcode) if postcode else ""
    found = [s for s in data.SPECIALISTS if s["specialty"] == spec and (hospital_list is None or hospital_list in s["lists"])]
    if not found:
        return {"specialty": spec, "specialists": [], "note": "No recognised specialist on this hospital list; a care adviser can help."}
    found.sort(key=lambda s: (0 if area and s["area"] == area else 1, 0 if s["fee_assured"] else 1, s["next_available_days"]))
    rows = [{"specialist_id": s["id"], "name": s["name"], "hospital": s["hospital"], "fee_assured": s["fee_assured"],
             "first_available": data.rel(s["next_available_days"]), "video_or_phone": s["remote"]} for s in found[:3]]
    return {"specialty": spec, "hospital_list": hospital_list, "specialists": rows,
            "note": "Fee-assured specialists bill within our limits, so there is no shortfall to pay."}


class PreAuthBody(BaseModel):
    policy_id: str
    condition: str
    treatment: str
    referral: str = "open_referral"  # open_referral | named_referral | direct_access | none
    specialist_id: str | None = None
    symptoms_started: str | None = None
    gp_first_seen: str | None = None
    patient_name: str | None = None


@router.post("/healthcare/pre-authorisations", response_model=None)
async def create_pre_auth(body: PreAuthBody, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(body.policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    if p["type"] != "health":
        return err(409, "not_applicable", "A cash plan does not pre-authorise treatment")
    condition, treatment = body.condition.strip(), body.treatment.strip()
    if len(condition) < 3 or len(treatment) < 3:
        return err(422, "details_required", "Give the condition and the treatment or test the specialist recommends")
    if not body.symptoms_started:
        return err(422, "symptoms_started_required", "Ask when the symptoms first started")
    elig = _eligibility(pid, p, condition, treatment)
    if not elig["covered"]:
        return err(409, "not_covered", elig["reason"])
    referral = norm_key(body.referral)
    if elig["referral_needed"] and referral not in ("open_referral", "named_referral"):
        return err(409, "referral_needed", "This needs a GP referral first; ask the GP for an open referral naming the type of specialist")
    specialist = None
    if body.specialist_id:
        specialist = next((s for s in data.SPECIALISTS if s["id"] == body.specialist_id.strip().upper()), None)
        if specialist is None:
            return err(404, "specialist_not_found", "Unknown specialist id; use find_specialists")
        if p["hospital_list"] not in specialist["lists"]:
            return err(409, "specialist_not_on_list", f"{specialist['hospital']} is not on the member's hospital list")
    pending = _matches(treatment, SURGERY_WORDS)
    code = f"PA-{data.PRE_AUTH_BASE + data.next_id('pre_auth')}"
    rec: dict[str, Any] = {"member": x_member_ref, "policy_id": pid, "service": treatment, "condition": condition,
                           "status": "pending" if pending else "approved", "consultant": specialist["name"] if specialist else None,
                           "hospital": specialist["hospital"] if specialist else None}
    if pending:
        rec.update(expected_decision_date_offset=2, notes="Waiting for the specialist's procedure code and fee estimate.")
    else:
        rec.update(decision_date=data.rel(0), valid_through=data.rel(90), notes=f"Covers the {treatment}.")
    data.PRE_AUTHS[code] = rec
    data.NEW_IDS["pre_auth"].append(code)
    out = {"pre_auth_code": code, "status": rec["status"], "policy_id": pid, "condition": condition, "treatment": treatment,
           "specialist": rec["consultant"], "hospital": rec["hospital"], "valid_through": rec.get("valid_through"),
           "excess_to_pay": elig["excess_remaining"], "forms_needed": elig["forms_needed"],
           "next_step": ("Give this code to the hospital or specialist when you book; they bill us directly, so you pay only any excess."
                         if not pending else "The specialist sends us the procedure code and fee estimate; we confirm within 2 working days. Do not book surgery until it is approved.")}
    if specialist and not specialist["fee_assured"]:
        out["shortfall_warning"] = "This specialist is not fee-assured: if they charge above our fee guidelines, you pay the difference."
    if elig.get("note"):
        out["note"] = elig["note"]
    return out


# ================================================================ sales: quotes, underwriting, applications (Health Cover Sales)
class Person(BaseModel):
    name: str | None = None
    date_of_birth: str
    smoker: bool = False
    relationship: str = "policyholder"  # policyholder | partner | child


class QuoteBody(BaseModel):
    people: list[Person] = Field(min_length=1)
    postcode: str
    start_date: str | None = None
    occupation: str | None = None


def _selection_valid(sel: dict[str, Any]) -> str | None:
    if sel["product"] not in data.PRODUCTS:
        return f"Choose a product: {', '.join(data.PRODUCTS)}"
    if sel["product"] == "essentials" and sel.get("outpatient_limit"):
        return "Northgate Essentials has no outpatient diagnostics, so it has no outpatient limit"
    if sel["product"] == "complete" and str(sel.get("outpatient_limit")) not in data.OUTPATIENT_LIMITS:
        return f"Choose an outpatient limit: {', '.join(data.OUTPATIENT_LIMITS)}"
    if sel["excess"] not in data.EXCESSES:
        return f"Choose an excess: {', '.join(f'£{e}' for e in data.EXCESSES)}"
    if sel["hospital_list"] not in data.HOSPITAL_LISTS:
        return f"Choose a hospital list: {', '.join(data.HOSPITAL_LISTS)}"
    bad = [a for a in sel.get("add_ons", []) if a not in data.ADD_ONS]
    if bad:
        return f"Unknown add-on {bad[0]}; choose from {', '.join(data.ADD_ONS)}"
    return None


def _price(q: dict[str, Any], sel: dict[str, Any], method_factor: float = 1.0) -> dict[str, Any]:
    product = data.PRODUCTS[sel["product"]]
    out_f = data.OUTPATIENT_LIMITS[str(sel["outpatient_limit"])] if sel["product"] == "complete" else 1.0
    factor = product["factor"] * out_f * data.EXCESSES[sel["excess"]] * data.HOSPITAL_LISTS[sel["hospital_list"]][0] * q["region_factor"] * method_factor
    people, core = [], 0.0
    for person in q["people"]:
        p = data.base_for_age(person["age"]) * factor * (data.SMOKER_LOADING if person["smoker"] else 1.0)
        core += p
        people.append({"name": person["name"], "age": person["age"], "core_monthly": money(p)})
    discount_rate = data.MULTI_PERSON_DISCOUNT.get(min(len(q["people"]), 3), 0.0)
    add_ons = sum(data.ADD_ONS[a][0] for a in sel.get("add_ons", [])) * len(q["people"])
    monthly = core * (1 - discount_rate) + add_ons
    return {"monthly_total": money(monthly), "annual_total": money(monthly * 12), "multi_person_discount_percent": int(discount_rate * 100),
            "add_ons_monthly": money(add_ons), "per_person": people}


def _describe(sel: dict[str, Any]) -> dict[str, Any]:
    return {"product": data.PRODUCTS[sel["product"]]["name"],
            "outpatient_limit": (f"£{int(sel['outpatient_limit']):,}" if sel["outpatient_limit"] not in (None, "unlimited") else sel["outpatient_limit"] or "not included"),
            "excess": f"£{sel['excess']}", "hospital_list": data.HOSPITAL_LISTS[sel["hospital_list"]][1],
            "add_ons": [data.ADD_ONS[a][1] for a in sel.get("add_ons", [])]}


def _quote_or_err(quote_id: str) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    q = data.QUOTES.get(norm_id(quote_id))
    if q is None:
        return None, err(404, "quote_not_found", "No quote with that reference")
    if date.fromisoformat(q["valid_until"]) < data.today():
        return None, err(409, "quote_expired", "The quote has expired; create a new one")
    return q, None


@router.post("/sales/quotes", response_model=None)
async def create_quote(body: QuoteBody) -> dict[str, Any] | JSONResponse:
    if len(body.people) > 6:
        return err(422, "too_many_people", "A family policy covers up to 6 people")
    start = parse_date(body.start_date) if body.start_date else data.today() + timedelta(days=1)
    if start is None or not data.today() <= start <= data.today() + timedelta(days=90):
        return err(422, "invalid_start_date", "Cover can start any day from today up to 90 days ahead")
    if not re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", body.postcode.strip().upper()):
        return err(422, "invalid_postcode", "Give a full UK postcode, for example LS6 2AB")
    people = []
    for i, person in enumerate(body.people):
        dob = parse_date(person.date_of_birth)
        if dob is None:
            return err(422, "invalid_date_of_birth", f"Could not read the date of birth of person {i + 1}")
        age = data.age_on(dob, start)
        rel = norm_key(person.relationship)
        if rel == "policyholder" and not 18 <= age <= 79:
            return err(422, "age_not_eligible", "The policyholder must be between 18 and 79 to join")
        if rel == "child" and age > 25:
            return err(422, "age_not_eligible", "Children can be covered up to age 25")
        people.append({"name": (person.name or f"Person {i + 1}").strip(), "dob": dob.isoformat(), "age": age, "smoker": person.smoker and age >= 16,
                       "relationship": rel})
    if not any(p["relationship"] == "policyholder" for p in people):
        people[0]["relationship"] = "policyholder"
    factor, region = data.region_of(body.postcode)
    qid = f"Q-{60000 + data.next_id('quote')}"
    q = {"quote_id": qid, "people": people, "postcode": body.postcode.strip().upper(), "region": region, "region_factor": factor,
         "start_date": start.isoformat(), "occupation": body.occupation, "valid_until": data.rel(data.QUOTE_VALID_DAYS), "selection": None}
    data.QUOTES[qid] = q
    packages = []
    for key, pk in data.PACKAGES.items():
        sel = {"product": pk["product"], "outpatient_limit": pk["outpatient_limit"], "excess": pk["excess"], "hospital_list": pk["hospital_list"], "add_ons": []}
        packages.append({"package": key, "label": pk["label"], **_describe(sel), **{k: v for k, v in _price(q, sel).items() if k in ("monthly_total", "annual_total")}})
    return {"quote_id": qid, "valid_until": q["valid_until"], "start_date": q["start_date"], "region": region,
            "people": [{"name": p["name"], "age": p["age"], "smoker": p["smoker"]} for p in people], "packages": packages,
            "note": "Prices are monthly by Direct Debit and assume moratorium underwriting; they are confirmed after the underwriting questions."}


class PriceBody(BaseModel):
    package: str | None = None
    product: str | None = None
    outpatient_limit: str | None = None
    excess: int | None = None
    hospital_list: str | None = None
    add_ons: list[str] = Field(default_factory=list)


@router.post("/sales/quotes/{quote_id}/price", response_model=None)
async def price_quote(quote_id: str, body: PriceBody) -> dict[str, Any] | JSONResponse:
    q, e = _quote_or_err(quote_id)
    if e:
        return e
    base = data.PACKAGES.get(norm_key(body.package)) if body.package else None
    if body.package and base is None:
        return err(422, "unknown_package", f"Choose a package: {', '.join(data.PACKAGES)}")
    sel = {"product": norm_key(body.product) if body.product else (base or {}).get("product", "complete"),
           "outpatient_limit": (body.outpatient_limit or "").replace("£", "").replace(",", "").strip().lower() or (base or {}).get("outpatient_limit"),
           "excess": body.excess if body.excess is not None else (base or {}).get("excess", 100),
           "hospital_list": norm_key(body.hospital_list) if body.hospital_list else (base or {}).get("hospital_list", "extended"),
           "add_ons": [norm_key(a) for a in body.add_ons]}
    if sel["product"] == "essentials":
        if body.outpatient_limit:
            return err(422, "invalid_option", "Northgate Essentials has no outpatient diagnostics, so it has no outpatient limit")
        sel["outpatient_limit"] = None
    elif not sel["outpatient_limit"]:
        sel["outpatient_limit"] = "unlimited"
    problem = _selection_valid(sel)
    if problem:
        return err(422, "invalid_option", problem)
    q["selection"] = sel
    return {"quote_id": q["quote_id"], "selection": _describe(sel), **_price(q, sel), "valid_until": q["valid_until"]}


class UnderwritingAnswer(BaseModel):
    person: str | int | None = None
    conditions: list[str] = Field(default_factory=list)
    hazardous_activities: bool = False


class UnderwritingBody(BaseModel):
    method: str
    answers: list[UnderwritingAnswer] = Field(default_factory=list)
    previous_insurer: str | None = None
    continuous_cover_months: int | None = None


def _person_index(q: dict[str, Any], who: str | int | None, default: int) -> int:
    if isinstance(who, int):
        return who if 0 <= who < len(q["people"]) else default
    if isinstance(who, str) and who.strip():
        t = who.strip().lower()
        for i, p in enumerate(q["people"]):
            if t in p["name"].lower() or p["name"].lower().split(" ")[0] == t.split(" ")[0]:
                return i
        if t.isdigit():
            return int(t) - 1 if 0 < int(t) <= len(q["people"]) else default
    return default


@router.post("/sales/quotes/{quote_id}/underwriting", response_model=None)
async def underwriting(quote_id: str, body: UnderwritingBody) -> dict[str, Any] | JSONResponse:
    q, e = _quote_or_err(quote_id)
    if e:
        return e
    if q["selection"] is None:
        return err(409, "no_cover_selected", "Price the chosen cover with price_quote first")
    method = norm_key(body.method)
    method = {"mori": "moratorium", "fmu": "full_medical", "full_medical_underwriting": "full_medical", "switch_insurer": "switch",
              "continued_cover": "switch", "cpme": "switch"}.get(method, method)
    if method not in data.UNDERWRITING_METHODS:
        return err(422, "unknown_method", "Choose moratorium, full_medical or switch")
    answers: dict[int, UnderwritingAnswer] = {}
    for n, a in enumerate(body.answers):
        answers[_person_index(q, a.person, n)] = a
    if method == "full_medical" and len(answers) < len(q["people"]):
        missing = [p["name"] for i, p in enumerate(q["people"]) if i not in answers]
        return err(422, "answers_required", "Full medical underwriting needs the health answers of everyone on the policy", missing=missing)
    if method == "switch" and (not body.previous_insurer or (body.continuous_cover_months or 0) < 12):
        return err(409, "switch_not_eligible", "Switching keeps your terms only with at least 12 months of continuous cover with another UK insurer; choose moratorium or full_medical")
    people, decision, refer_reasons = [], "accept", []
    for i, p in enumerate(q["people"]):
        a = answers.get(i) or UnderwritingAnswer()
        score = 10 + (p["age"] // 10) * 3 + (15 if p["smoker"] else 0) + (data.HAZARD_POINTS if a.hazardous_activities else 0)
        exclusions: list[str] = []
        if method == "full_medical":
            for c in a.conditions:
                c = c.strip()
                if not c or c.lower() in ("none", "no"):
                    continue
                score += 12
                if _matches(c, data.SERIOUS_CONDITIONS):
                    refer_reasons.append(f"{p['name']}: {c}")
                exclusions.append(f"{c} and related conditions")
        band = "low" if score < 40 else "medium" if score < 60 else "high"
        people.append({"name": p["name"], "risk_score": min(score, 100), "risk_band": band, "exclusions": exclusions})
        if exclusions and decision == "accept":
            decision = "accept_with_exclusions"
        if score >= 80:
            refer_reasons.append(f"{p['name']}: risk score {score}")
    if refer_reasons:
        decision = "refer_to_underwriter"
    method_factor = 0.95 if method == "full_medical" else 1.0
    uid = f"UW-{70000 + data.next_id('uw')}"
    price = _price(q, q["selection"], method_factor)
    rec = {"underwriting_id": uid, "quote_id": q["quote_id"], "method": method, "method_explained": data.UNDERWRITING_METHODS[method],
           "decision": decision, "people": people, "monthly_total": price["monthly_total"], "annual_total": price["annual_total"]}
    if method == "switch":
        rec["previous_insurer"] = body.previous_insurer
    if decision == "refer_to_underwriter":
        rec["next_step"] = "An underwriter must review this before cover can start; hand over to a person. Do not promise cover."
        rec["refer_reasons"] = refer_reasons
    elif decision == "accept_with_exclusions":
        rec["next_step"] = "Read each exclusion to the caller and confirm they are happy before the application."
    else:
        rec["next_step"] = "Read the key facts, then ask for consent to create the policy."
    data.UNDERWRITING[uid] = rec
    return rec


class Policyholder(BaseModel):
    first_name: str
    last_name: str
    email: str
    mobile: str
    address: str


class ApplicationBody(BaseModel):
    quote_id: str
    underwriting_id: str
    policyholder: Policyholder
    documents_by: str = "email"
    payment_link_by: str = "sms"
    key_facts_confirmed: bool = False
    declaration_confirmed: bool = False
    marketing_opt_in: bool = False


@router.post("/sales/applications", response_model=None)
async def create_application(body: ApplicationBody) -> dict[str, Any] | JSONResponse:
    q, e = _quote_or_err(body.quote_id)
    if e:
        return e
    uw = data.UNDERWRITING.get(norm_id(body.underwriting_id))
    if uw is None or uw["quote_id"] != q["quote_id"]:
        return err(404, "underwriting_not_found", "No underwriting result for this quote; run assess_underwriting first")
    if uw["decision"] == "refer_to_underwriter":
        return err(409, "referred_to_underwriter", "This application needs an underwriter; hand over to a person")
    if not body.key_facts_confirmed or not body.declaration_confirmed:
        return err(422, "confirmation_required", "Read the key facts and the declaration, and get a clear yes to both, before creating the policy")
    ph = body.policyholder
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", ph.email.strip()):
        return err(422, "invalid_email", "That does not look like an email address")
    if not re.fullmatch(r"(\+44|0)7\d{9}", re.sub(r"[\s\-()]", "", ph.mobile)):
        return err(422, "invalid_mobile", "Give a UK mobile number starting 07")
    docs_by, link_by = body.documents_by.strip().lower(), body.payment_link_by.strip().lower()
    if docs_by not in ("email", "sms") or link_by not in ("email", "sms"):
        return err(422, "invalid_channel", "Send documents and the Direct Debit link by email or sms")
    if q.get("application_id"):
        prior = data.APPLICATIONS[q["application_id"]]
        return err(409, "already_applied", "A policy was already created from this quote", policy_id=prior["policy_id"])
    pid = f"PMI-{310000 + data.next_id('policy')}"
    holder = next(p for p in q["people"] if p["relationship"] == "policyholder")
    member_ref = f"{data.MEMBER_PREFIX}-{960000 + data.next_id('member')}"
    sel = q["selection"]
    data.MEMBERS[member_ref] = {"first_name": ph.first_name.strip(), "last_name": ph.last_name.strip(), "dob": holder["dob"],
                                "plan": data.PRODUCTS[sel["product"]]["name"], "email": ph.email.strip(), "mobile": ph.mobile.strip(), "address": ph.address.strip()}
    data.NEW_IDS["member"].append(member_ref)
    start = date.fromisoformat(q["start_date"])
    data.POLICIES[pid] = {"member": member_ref, "type": "health", "product": data.PRODUCTS[sel["product"]]["name"], "status": "active_pending_direct_debit",
                          "start_date": start.isoformat(), "renewal_date": (start + timedelta(days=365)).isoformat(), "monthly_premium": uw["monthly_total"],
                          "payment_method": "Direct Debit", "insured_persons": [p["name"] for p in q["people"]], "excess": sel["excess"],
                          "outpatient_limit": sel["outpatient_limit"], "hospital_list": sel["hospital_list"], "underwriting": uw["method"],
                          "add_ons": sel["add_ons"], "cooling_off_ends": (start + timedelta(days=21)).isoformat()}
    first_collection = start + timedelta(days=10)
    data.PAYMENTS[pid] = {"collection_day": min(first_collection.day, 28), "status": "awaiting_direct_debit", "next_collection_date": first_collection.isoformat(),
                          "amount": uw["monthly_total"], "bank_account": "not set up yet", "history": [], "missed_amount": 0.0, "reinstate_by": None}
    exclusions = [x for p in uw["people"] for x in p["exclusions"]]
    if exclusions:
        data.EXCLUSIONS[pid] = exclusions
    app_id = f"APP-{pid.split('-')[1]}"
    q["application_id"] = app_id
    sent = {"email": mask_email(ph.email.strip()), "sms": mask_phone(ph.mobile)}
    out = {"application_id": app_id, "policy_id": pid, "membership_number": member_ref, "status": "active_pending_direct_debit",
           "cover": _describe(sel), "underwriting": uw["method"], "exclusions": exclusions, "monthly_premium": uw["monthly_total"],
           "start_date": start.isoformat(), "first_collection_date": first_collection.isoformat(), "cooling_off_ends": data.POLICIES[pid]["cooling_off_ends"],
           "documents_sent_to": sent[docs_by], "direct_debit_link_sent_to": sent[link_by],
           "next_step": "Set up the Direct Debit with the secure link within 7 days. The welcome pack (membership certificate, policy guide and key facts) is on its way."}
    data.APPLICATIONS[app_id] = {**out, "quote_id": q["quote_id"], "marketing_opt_in": body.marketing_opt_in}
    return out


# ================================================================ outreach (outbound call targets)
@router.get("/insurance/outreach/renewals")
async def outreach_renewals() -> dict[str, Any]:
    """Members whose health policy renews within 60 days (used by outbound agents built in the Studio)."""
    targets = []
    for pid, p in data.POLICIES.items():
        days = (date.fromisoformat(p["renewal_date"]) - data.today()).days
        if p["type"] != "health" or not 0 <= days <= 60 or p["member"] in data.NEW_IDS["member"]:
            continue
        m = data.MEMBERS[p["member"]]
        targets.append({
            "member_ref": p["member"], "first_name": m["first_name"],
            "summary": f"{p['product']} policy {pid} renews in {days} days",
            "context": {"member_id": p["member"].split("-")[1], "policy_id": pid, "product": p["product"], "renewal_date": p["renewal_date"],
                        "days_to_renewal": days, "purpose": "your upcoming policy renewal"},
        })
    targets.sort(key=lambda t: t["context"]["days_to_renewal"])
    return {"targets": targets}
