"""Mock healthcare, insurance and internal business API, called by agents as tools.

Spec: /api/mock-healthcare-api.md, /demo-data/members-and-claims.md
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from voiceai.modules.businessmock import data

router = APIRouter(prefix="/mock", tags=["mock"])

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


# ---------------------------------------------------------------- normalization
def norm_member(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    s = s.removeprefix("EVG")
    return f"EVG-{s}" if s.isdigit() else None


def norm_id(raw: str) -> str:
    """c20931 -> C-20931, hp100231 -> HP-100231, PA-77930 stays."""
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    m = re.fullmatch(r"([A-Z]+)(\d+)", s)
    return f"{m.group(1)}-{m.group(2)}" if m else raw.strip().upper()


def norm_key(raw: str) -> str:
    return re.sub(r"[\s\-]+", "_", raw.strip().lower())


def parse_date(raw: str) -> date | None:
    s = raw.strip().lower().replace(",", " ")
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    s = re.sub(r"\s+", " ", s)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    words = s.split(" ")
    try:
        if len(words) == 3 and words[0] in MONTHS:  # april 12 1986
            return date(int(words[2]), MONTHS[words[0]], int(words[1]))
        if len(words) == 3 and words[1] in MONTHS:  # 12 april 1986
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


def _decision_date(rec: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in rec.items() if k not in ("member", "expected_decision_date_offset")}
    if "expected_decision_date_offset" in rec:
        out["expected_decision_date"] = data.rel(rec["expected_decision_date_offset"])
    return out


def _owned_policy(policy_id: str, member: str) -> tuple[str, dict[str, Any] | None]:
    pid = norm_id(policy_id)
    p = data.POLICIES.get(pid)
    return pid, (p if p and p["member"] == member else None)


# ================================================================ member services
class VerifyBody(BaseModel):
    member_id: str
    date_of_birth: str


@router.post("/healthcare/verify")
async def verify(body: VerifyBody) -> dict[str, Any]:
    ref = norm_member(body.member_id)
    member = data.MEMBERS.get(ref or "")
    dob = parse_date(body.date_of_birth)
    if not member or not dob or dob.isoformat() != member["dob"]:
        return {"verified": False, "reason": "Member ID and date of birth do not match our records."}
    return {"verified": True, "member_ref": ref, "first_name": member["first_name"], "plan_name": member["plan"]}


@router.get("/healthcare/benefits", response_model=None)
async def benefits(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    member = data.MEMBERS.get(x_member_ref or "")
    if not member:
        return unverified()
    plan = data.PLANS[member["plan"]]
    return {
        "plan_name": member["plan"], "plan_type": plan["type"],
        "deductible": {"individual": plan["deductible"], "met": member["ded_met"], "remaining": max(plan["deductible"] - member["ded_met"], 0)},
        "out_of_pocket_max": {"individual": plan["oop_max"], "met": member["oop_met"], "remaining": max(plan["oop_max"] - member["oop_met"], 0)},
        "copays": plan["copays"], "referral_required_for_specialists": plan["referral"],
    }


@router.get("/healthcare/claims", response_model=None)
async def member_claims(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    claims = [
        {"claim_id": cid, "type": c["type"], "service": c["service"], "service_date": c["service_date"], "status": c["status"]}
        for cid, c in data.CLAIMS.items() if c["member"] == x_member_ref
    ]
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
    for k in ("plan_paid", "member_responsibility", "paid_date", "denial_reason", "appeal_deadline", "expected_decision_date", "notes"):
        out.setdefault(k, None)
    return out


@router.get("/healthcare/prior-auths/{auth_id}", response_model=None)
async def prior_auth(auth_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    aid = norm_id(auth_id)
    a = data.PRIOR_AUTHS.get(aid)
    if not a or a["member"] != x_member_ref:
        return err(404, "authorization_not_found", "No authorization with that number for this member")
    out = {"auth_id": aid, **_decision_date(a)}
    for k in ("decision_date", "valid_through", "expected_decision_date", "notes"):
        out.setdefault(k, None)
    return out


@router.get("/healthcare/providers")
async def providers(specialty: str = "", zip: str | None = None) -> dict[str, Any]:  # noqa: A002
    spec = specialty.strip().lower()
    found = [p for p in data.PROVIDERS if not spec or spec in p["specialty"].lower() or (spec == "dentist" and p["specialty"] == "Dentistry")]
    found.sort(key=lambda p: (0 if zip and p["zip"] == zip.strip() else 1, p["name"]))
    return {"providers": [{**p, "network": "in-network"} for p in found]}


# ================================================================ insurance: policies and coverage
@router.get("/insurance/policies", response_model=None)
async def policies(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    rows = [{"policy_id": pid, "type": p["type"], "product": p["product"], "status": p["status"], "start_date": p["start_date"], "renewal_date": p["renewal_date"]}
            for pid, p in data.POLICIES.items() if p["member"] == x_member_ref]
    return {"policies": sorted(rows, key=lambda r: (r["type"], r["policy_id"]))}


@router.get("/insurance/policies/{policy_id}", response_model=None)
async def policy(policy_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    member = data.MEMBERS[x_member_ref]
    out = {"policy_id": pid, **{k: v for k, v in p.items() if k != "member"}, "insured_persons": [f"{member['first_name']} {member['last_name']}"]}
    if p["type"] == "health":
        out["deductible"] = data.PLANS[p["product"]]["deductible"]
    return out


@router.get("/insurance/policies/{policy_id}/coverage", response_model=None)
async def coverage(policy_id: str, benefit: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    if p["type"] != "health":
        return err(409, "not_applicable", "Benefit and limit lookups apply to health policies")
    key = norm_key(benefit)
    key = data.BENEFIT_ALIASES.get(key, key)
    table = data.BENEFITS[p["product"]]
    if key not in table:
        return err(422, "unknown_benefit", "Unknown benefit", benefits=sorted(table))
    covered, limit, copay, wait, preauth, notes = table[key]
    used = data.USAGE.get(x_member_ref, {}).get(key, 0)
    return {
        "policy_id": pid, "benefit": key, "covered": covered, "annual_limit": limit, "used": used if covered else 0,
        "remaining": (max(limit - used, 0) if limit is not None else None) if covered else None,
        "waiting_period_days": wait, "pre_authorization_required": preauth, "copay_percent": copay,
        "notes": notes or ("No annual limit." if covered and limit is None else ""),
    }


# ================================================================ insurance: documents and Green Card
@router.get("/insurance/documents", response_model=None)
async def documents(policy_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    docs = [{"document_type": k, "title": title, "delivery_options": list(delivery)}
            for k, (title, types, delivery) in data.DOCUMENT_TYPES.items() if p["type"] in types]
    return {"policy_id": pid, "documents": docs}


class DocumentRequest(BaseModel):
    policy_id: str
    document_type: str
    delivery: str
    countries: list[str] | str | None = None
    travel_start: str | None = None
    travel_end: str | None = None


def _countries(raw: list[str] | str | None) -> list[str]:
    items = re.split(r",| and ", raw) if isinstance(raw, str) else (raw or [])
    return [re.sub(r"^the\s+", "", i.strip(), flags=re.I) for i in items if i and i.strip()]


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
        if dtype == "green_card":
            return err(409, "not_a_motor_policy", "A Green Card is only available for motor policies")  # MOCK-08
        return err(409, "document_not_available", f"'{body.document_type}' is not available for a {p['type']} policy")
    if delivery not in spec[2]:
        return err(409, "delivery_not_available", f"Delivery by {delivery} is not available for this document", options=list(spec[2]))
    extra: dict[str, Any] = {}
    if dtype == "green_card":
        if p["status"] != "active":
            return err(409, "policy_not_active", "The policy is not active")
        wanted = _countries(body.countries)
        if not wanted or not body.travel_start or not body.travel_end:
            return err(422, "missing_travel_details", "A Green Card needs destination countries, travel start and travel end dates")
        covered = {c.lower(): c for c in data.GREEN_CARD_COUNTRIES}
        unsupported = [c for c in wanted if c.lower() not in covered]
        if unsupported:
            return err(409, "country_not_covered", "Some destinations are not covered by the Green Card", unsupported_countries=unsupported, covered_countries=data.GREEN_CARD_COUNTRIES)
        start, end = parse_date(body.travel_start), parse_date(body.travel_end)
        if not start or not end or end < start or (end - start).days + 1 > 90 or not (data.today() <= start <= data.today() + timedelta(days=60)):
            return err(422, "invalid_travel_dates", "Travel must start between today and 60 days ahead and last at most 90 days")
        extra = {"valid_from": start.isoformat(), "valid_to": end.isoformat(), "countries": [covered[c.lower()] for c in wanted]}
    rid = f"DOC-{data.next_id('doc'):05d}"
    out: dict[str, Any] = {"request_id": rid, "document_type": dtype, "delivery": delivery, "eta": data.DOCUMENT_ETA[delivery], **extra}
    if delivery == "email":
        out.update(status="queued", sent_to=mask_email(data.MEMBERS[x_member_ref]["email"]))
    elif delivery == "download":
        out.update(status="ready", download_url=f"https://portal.evergreen.example/docs/{rid}")
    else:
        out.update(status="scheduled", sent_to="the address on file")
    data.DOCUMENT_REQUESTS.append({**out, "member": x_member_ref, "policy_id": pid})
    return out


# ================================================================ insurance: renewals
def _quote(pid: str, p: dict[str, Any]) -> dict[str, Any] | None:
    if pid not in data.QUOTES:
        return None
    days = (date.fromisoformat(p["renewal_date"]) - data.today()).days
    if not 0 <= days <= 90:
        return None
    premium, reasons, options = data.QUOTES[pid]
    current = p["annual_premium"]
    return {"policy_id": pid, "product": p["product"], "renewal_date": p["renewal_date"], "days_to_renewal": days, "current_premium": current,
            "renewal_premium": premium, "change_percent": round((premium - current) / current * 100, 1), "reasons": reasons,
            "options": options, "renewal_status": p["renewal_status"]}


@router.get("/insurance/policies/{policy_id}/renewal-quote", response_model=None)
async def renewal_quote(policy_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    q = _quote(pid, p)
    if q is None:
        return err(409, "not_in_renewal_window", "This policy is not within 90 days of renewal")
    return q


class RenewalDecision(BaseModel):
    decision: str
    option: str | None = None
    callback_time: str | None = None
    note: str | None = None


@router.post("/insurance/policies/{policy_id}/renewal-decision", response_model=None)
async def renewal_decision(policy_id: str, body: RenewalDecision, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    pid, p = _owned_policy(policy_id, x_member_ref)
    if p is None:
        return err(404, "policy_not_found", "No policy with that number for this member")
    decision = body.decision.strip().lower()
    if decision not in ("accept", "decline", "callback"):
        return err(422, "invalid_decision", "decision must be accept, decline or callback")
    if decision == "callback" and not (body.callback_time or "").strip():
        return err(422, "callback_time_required", "A callback needs a time")  # MOCK-09
    p["renewal_status"] = {"accept": "accepted", "decline": "declined", "callback": "callback_requested"}[decision]
    ref = f"RN-{data.next_id('renewal'):05d}"
    data.RENEWAL_DECISIONS.append({"reference": ref, "policy_id": pid, "decision": decision, "option": body.option, "callback_time": body.callback_time, "note": body.note})
    return {"reference": ref, "policy_id": pid, "renewal_status": p["renewal_status"]}


# ================================================================ insurance: onboarding
def _checklist(member: str) -> dict[str, Any]:
    rec = data.ONBOARDING.get(member)
    if rec is None:
        return {"policy_id": None, "status": "complete", "steps": [], "remaining": 0}
    steps = [{"step_id": sid, "title": data.ONBOARDING_STEPS[sid], "status": status} for sid, status in rec["steps"].items()]
    remaining = sum(1 for s in steps if s["status"] == "pending")
    return {"policy_id": rec["policy_id"], "status": "in_progress" if remaining else "complete", "steps": steps, "remaining": remaining}


@router.get("/insurance/onboarding", response_model=None)
async def onboarding(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    return _checklist(x_member_ref)


class StepBody(BaseModel):
    value: str | None = None


@router.post("/insurance/onboarding/steps/{step_id}", response_model=None)
async def complete_step(step_id: str, body: StepBody | None = None, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return unverified()
    rec = data.ONBOARDING.get(x_member_ref)
    sid = norm_key(step_id)
    if rec is None or sid not in rec["steps"]:
        return err(404, "step_not_found", "Unknown onboarding step", steps=list(data.ONBOARDING_STEPS))
    value = (body.value if body else None) or ""
    if sid == "communication_preferences":
        if value.strip().lower() not in data.COMMUNICATION_PREFERENCES:
            return err(422, "invalid_preference", "value must be email, sms or post")
        rec["preferences"] = value.strip().lower()
    rec["steps"][sid] = "done"
    return _checklist(x_member_ref)


# ================================================================ insurance: outreach target lists
@router.get("/insurance/outreach/renewals")
async def outreach_renewals() -> dict[str, Any]:
    targets = []
    for pid, p in data.POLICIES.items():
        q = _quote(pid, p)
        if q is None or p["renewal_status"] != "pending" or q["days_to_renewal"] > 60:
            continue
        m = data.MEMBERS[p["member"]]
        kind = "motor" if p["type"] == "motor" else "health"
        targets.append({
            "member_ref": p["member"], "first_name": m["first_name"],
            "summary": f"{kind.title()} policy {pid} renews in {q['days_to_renewal']} days ({q['change_percent']:+.1f}%)",
            "context": {"member_id": p["member"].split("-")[1], "policy_id": pid, "product": p["product"], "renewal_date": p["renewal_date"],
                        "days_to_renewal": q["days_to_renewal"], "premium_change_percent": q["change_percent"], "purpose": "your upcoming policy renewal"},
        })
    targets.sort(key=lambda t: t["context"]["days_to_renewal"])
    return {"targets": targets}


@router.get("/insurance/outreach/onboarding")
async def outreach_onboarding() -> dict[str, Any]:
    targets = []
    for member_ref in data.ONBOARDING:
        c = _checklist(member_ref)
        if not c["remaining"]:
            continue
        m = data.MEMBERS[member_ref]
        targets.append({
            "member_ref": member_ref, "first_name": m["first_name"],
            "summary": f"{data.POLICIES[c['policy_id']]['product']}, {c['remaining']} onboarding steps left",
            "context": {"member_id": member_ref.split("-")[1], "policy_id": c["policy_id"], "product": data.POLICIES[c["policy_id"]]["product"],
                        "steps_remaining": c["remaining"], "purpose": "getting you set up with your new plan"},
        })
    return {"targets": sorted(targets, key=lambda t: t["context"]["steps_remaining"], reverse=True)}


# ================================================================ internal reference data
@router.get("/internal/authorization-limits", response_model=None)
async def authorization_limits(role: str | None = None, claim_type: str | None = None) -> dict[str, Any] | JSONResponse:
    if role is None:
        return {"roles": data.AUTH_LIMITS}
    key = norm_key(role)
    if key not in data.AUTH_LIMITS:
        return err(404, "role_not_found", "Unknown role", roles=sorted(data.AUTH_LIMITS))
    if claim_type is None:
        return {"role": key, "limits": data.AUTH_LIMITS[key]}
    ctype = norm_key(claim_type)
    if ctype not in data.AUTH_LIMITS[key]:
        return err(404, "claim_type_not_found", "Unknown claim type", claim_types=sorted(data.AUTH_LIMITS[key]))
    limit = data.AUTH_LIMITS[key][ctype]
    return {"role": key, "claim_type": ctype, "limit": limit, "cosign_required_above": limit if key == "claims_manager" else None}


@router.get("/internal/contacts", response_model=None)
async def contacts(topic: str) -> dict[str, Any] | JSONResponse:
    key = norm_key(topic)
    if key not in data.CONTACTS:
        return err(404, "topic_not_found", "Unknown topic", topics=sorted(data.CONTACTS))  # MOCK-12
    team, ext, hours, email = data.CONTACTS[key]
    return {"topic": key, "team": team, "contact": team, "extension": ext, "hours": hours, "email": email}
