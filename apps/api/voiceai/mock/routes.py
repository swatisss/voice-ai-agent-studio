"""Mock healthcare and pharmacy business API, called by agents as tools.

Spec: /api/mock-healthcare-api.md
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from voiceai.db import new_id
from voiceai.mock import data

router = APIRouter(prefix="/mock", tags=["mock"])

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def norm_member(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    s = s.removeprefix("EVG")
    return f"EVG-{s}" if s.isdigit() else None


def norm_ref(raw: str, prefix: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if s.startswith(prefix):
        s = s[len(prefix):]
    return f"{prefix}-{s}"


def parse_dob(raw: str) -> date | None:
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


def _unverified() -> JSONResponse:
    return JSONResponse({"error": "member_not_verified", "detail": "Verify the member first"}, status_code=401)


def _not_found(what: str) -> JSONResponse:
    return JSONResponse({"error": f"{what}_not_found", "detail": f"No {what} with that number for this member"}, status_code=404)


class VerifyBody(BaseModel):
    member_id: str
    date_of_birth: str


@router.post("/healthcare/verify")
async def verify(body: VerifyBody) -> dict[str, Any]:
    ref = norm_member(body.member_id)
    member = data.MEMBERS.get(ref or "")
    dob = parse_dob(body.date_of_birth)
    if not member or not dob or dob.isoformat() != member["dob"]:
        return {"verified": False, "reason": "Member ID and date of birth do not match our records."}
    return {"verified": True, "member_ref": ref, "first_name": member["first_name"], "plan_name": member["plan"]}


@router.get("/healthcare/benefits", response_model=None)
async def benefits(x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    member = data.MEMBERS.get(x_member_ref or "")
    if not member:
        return _unverified()
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
        return _unverified()
    claims = [
        {"claim_id": cid, "service": c["service"], "service_date": c["service_date"], "status": c["status"]}
        for cid, c in data.CLAIMS.items() if c["member"] == x_member_ref
    ]
    return {"claims": sorted(claims, key=lambda c: c["service_date"], reverse=True)}


@router.get("/healthcare/claims/{claim_id}", response_model=None)
async def claim(claim_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return _unverified()
    cid = norm_ref(claim_id, "C")
    c = data.CLAIMS.get(cid)
    if not c or c["member"] != x_member_ref:
        return _not_found("claim")
    out = {"claim_id": cid, **{k: v for k, v in c.items() if k != "member"}}
    for k in ("plan_paid", "member_responsibility", "paid_date", "denial_reason", "appeal_deadline", "expected_decision_date", "notes"):
        out.setdefault(k, None)
    return out


@router.get("/healthcare/prior-auths/{auth_id}", response_model=None)
async def prior_auth(auth_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return _unverified()
    aid = norm_ref(auth_id, "PA")
    a = data.PRIOR_AUTHS.get(aid)
    if not a or a["member"] != x_member_ref:
        return _not_found("authorization")
    out = {"auth_id": aid, **{k: v for k, v in a.items() if k != "member"}}
    for k in ("decision_date", "valid_through", "expected_decision_date", "notes"):
        out.setdefault(k, None)
    return out


@router.get("/healthcare/providers")
async def providers(specialty: str = "", zip: str | None = None) -> dict[str, Any]:  # noqa: A002
    spec = specialty.strip().lower()
    found = [p for p in data.PROVIDERS if not spec or spec in p["specialty"].lower()]
    found.sort(key=lambda p: (0 if zip and p["zip"] == zip.strip() else 1, p["name"]))
    return {"providers": [{**p, "network": "in-network"} for p in found]}


class IdCardBody(BaseModel):
    reason: str | None = None


@router.post("/healthcare/id-card", response_model=None)
async def id_card(body: IdCardBody | None = None, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return _unverified()
    return {"request_id": f"IDC-{new_id()[:8].upper()}", "mail_eta_business_days": "7-10", "digital_card_available": True}


@router.get("/pharmacy/formulary", response_model=None)
async def formulary(drug: str) -> dict[str, Any] | JSONResponse:
    q = drug.strip().lower()
    for name, entry in data.FORMULARY.items():
        if q in (name, str(entry.get("brand", "")).lower()):
            return {"drug": name, **entry}
    return JSONResponse({"error": "drug_not_found", "detail": "That drug is not on the formulary"}, status_code=404)


@router.get("/pharmacy/refills/{rx_id}", response_model=None)
async def refill(rx_id: str, x_member_ref: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    if x_member_ref not in data.MEMBERS:
        return _unverified()
    rid = norm_ref(rx_id, "RX")
    r = data.REFILLS.get(rid)
    if not r or r["member"] != x_member_ref:
        return _not_found("prescription")
    return {"rx_id": rid, **{k: v for k, v in r.items() if k != "member"}}
