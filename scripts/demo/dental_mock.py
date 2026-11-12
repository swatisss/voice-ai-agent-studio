"""A mock Oakhaven Dental Care patient system for the dental demo kit: patients, slots, bookings, cover, estimates, claims.

Oakhaven is fictional and every record is synthetic. Prices, limits and waiting periods match the kit's knowledge files
(scripts/demo/dental/knowledge/). State lives in memory and resets when the server stops. The platform's HTTP tools call
it with the verified patient in `X-Member-Ref`, like the built-in mock APIs (/architecture/tools-and-skills.md).

    python scripts/demo/dental_mock.py --port 8766      # on its own; scripts/demo_kits.py dental starts it for you
"""
from __future__ import annotations

import argparse
import http.server
import json
import re
import threading
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

PRACTICES = {
    "leeds": {"name": "Oakhaven Leeds", "address": "14 Wren Street, Leeds LS1 2QX", "phone": "0113 496 0120"},
    "manchester": {"name": "Oakhaven Manchester", "address": "3 Mill Yard, Manchester M2 4WL", "phone": "0161 496 0130"},
    "bristol": {"name": "Oakhaven Bristol", "address": "22 Harbourside Walk, Bristol BS1 5TY", "phone": "0117 496 0140"},
}
SEDATION_PRACTICES = {"leeds", "manchester"}

# appointment type -> (minutes, price guide)
APPOINTMENT_TYPES = {
    "check_up": (20, "£55"), "hygiene": (30, "£75"), "new_patient_exam": (40, "£75"), "emergency": (20, "£85"),
    "filling": (45, "from £140"), "consultation": (30, "free"), "sedation_consultation": (30, "free"),
}
TYPE_ALIASES = {"checkup": "check_up", "check": "check_up", "exam": "check_up", "scale_and_polish": "hygiene", "hygienist": "hygiene",
                "clean": "hygiene", "cleaning": "hygiene", "new_patient": "new_patient_exam", "new_patient_examination": "new_patient_exam",
                "emergency_appointment": "emergency", "urgent": "emergency", "treatment_consultation": "consultation"}

# treatment -> (price in pounds, insurance category, "from" price)
TREATMENTS: dict[str, tuple[int, str, bool]] = {
    "check_up": (55, "routine", False), "hygiene": (75, "routine", False), "new_patient_exam": (75, "routine", False),
    "emergency_appointment": (85, "routine", False),
    "white_filling_small": (140, "restorative", True), "white_filling_large": (190, "restorative", False),
    "simple_extraction": (150, "restorative", False), "surgical_extraction": (325, "restorative", False),
    "root_canal_front": (395, "restorative", False), "root_canal_premolar": (495, "restorative", False),
    "root_canal_molar": (695, "restorative", False),
    "crown": (795, "major", False), "bridge": (1500, "major", True), "implant": (2600, "major", True),
    "whitening": (395, "cosmetic", False), "clear_aligners": (2950, "cosmetic", True), "sedation": (295, "sedation", False),
}
TREATMENT_ALIASES = {"checkup": "check_up", "filling": "white_filling_small", "white_filling": "white_filling_small",
                     "extraction": "simple_extraction", "wisdom_tooth": "surgical_extraction", "wisdom_tooth_extraction": "surgical_extraction",
                     "porcelain_crown": "crown", "dental_implant": "implant", "teeth_whitening": "whitening", "aligners": "clear_aligners",
                     "emergency": "emergency_appointment", "iv_sedation": "sedation", "scale_and_polish": "hygiene"}

# Oakhaven Dental Insurance: category -> (share paid, annual limit) per level
LEVELS = {
    "Level 1": {"routine": (1.0, 150), "restorative": (0.5, 300)},
    "Level 2": {"routine": (1.0, 250), "restorative": (0.75, 700), "major": (0.5, 1000)},
    "Level 3": {"routine": (1.0, 350), "restorative": (0.8, 1200), "major": (0.6, 2000)},
}
WAITING_MONTHS = {"routine": 0, "restorative": 3, "major": 12}
CARE_PLANS = {"Essential": {"monthly": "£14.50", "discount": 0.10, "check_ups": 2, "hygiene": 1, "emergency_included": False},
              "Plus": {"monthly": "£21", "discount": 0.15, "check_ups": 2, "hygiene": 2, "emergency_included": True}}

PATIENTS: dict[str, dict[str, Any]] = {
    "OD-10231": {"first_name": "Priya", "last_name": "Shah", "dob": "1988-04-12", "practice": "leeds",
                 "insurance": {"level": "Level 2", "start": "2026-07-01", "used": {"routine": 55}}},
    "OD-10457": {"first_name": "Tom", "last_name": "Walsh", "dob": "1975-09-30", "practice": "manchester",
                 "insurance": {"level": "Level 3", "start": "2023-03-15", "used": {"routine": 130, "restorative": 316}}},
    "OD-10822": {"first_name": "Grace", "last_name": "Ellison", "dob": "1994-11-02", "practice": "bristol",
                 "care_plan": {"plan": "Plus", "start": "2025-02-01", "used": {"check_ups": 1, "hygiene": 1}}},
}
CLAIMS = {
    "DC-5531": {"patient": "OD-10457", "treatment": "Root canal treatment, front tooth", "treatment_date": "2026-09-18", "amount": 395,
                "status": "paid", "paid": 316.0, "paid_on": "2026-10-02", "note": "Paid at 80% under Level 3 restorative cover."},
    "DC-5560": {"patient": "OD-10457", "treatment": "White filling", "treatment_date": "2026-10-27", "amount": 140,
                "status": "more_information_needed", "paid": 0.0,
                "note": "We need the dentist's itemised receipt showing the treatment, the date and the cost. Upload it in the Oakhaven app."},
    "DC-5512": {"patient": "OD-10457", "treatment": "Home teeth whitening", "treatment_date": "2026-06-03", "amount": 395,
                "status": "declined", "paid": 0.0,
                "note": "Cosmetic treatment such as teeth whitening is not covered. You can ask for a review within 8 weeks of this decision."},
    "DC-6104": {"patient": "OD-10231", "treatment": "Routine check-up", "treatment_date": "2026-11-02", "amount": 55,
                "status": "received", "paid": 0.0, "note": "We will review it within 5 working days."},
}


# ------------------------------------------------------------------ helpers
def norm_patient(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return f"OD-{digits}" if digits else ""


def parse_dob(raw: str) -> str | None:
    """ISO, UK day-first (12/04/1988) or spoken ('12 April 1988', 'April 12, 1988')."""
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", (raw or "").strip()).replace(",", "")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def key(raw: str, aliases: dict[str, str]) -> str:
    k = re.sub(r"[^a-z0-9]+", "_", (raw or "").lower()).strip("_")
    return aliases.get(k, k)


def practice_key(raw: str) -> str | None:
    text = (raw or "").lower()
    return next((p for p in PRACTICES if p in text), None)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def is_open(practice: str, d: date) -> bool:
    return d.weekday() < 5 or (d.weekday() == 5 and practice != "leeds")


def times(practice: str, d: date, appt: str) -> list[str]:
    if appt == "emergency":
        return ["12:15"] if d.weekday() == 5 else ["11:45", "15:15"]
    if d.weekday() == 5:
        return ["09:30", "11:00"]
    return ["09:00", "10:30", "14:00", "16:00"] + (["18:30"] if practice == "leeds" and d.weekday() == 3 else [])


def slot_id(practice: str, d: date, t: str) -> str:
    return f"{practice[:3].upper()}-{d:%Y%m%d}-{t.replace(':', '')}"


def parse_slot(sid: str) -> tuple[str, datetime] | None:
    m = re.fullmatch(r"(LEE|MAN|BRI)-(\d{8})-(\d{4})", (sid or "").strip().upper())
    if not m:
        return None
    practice = {"LEE": "leeds", "MAN": "manchester", "BRI": "bristol"}[m.group(1)]
    return practice, datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M")


def benefit_year(start: date, today: date) -> tuple[date, date]:
    begin = date(today.year, start.month, min(start.day, 28))
    if begin > today:
        begin = date(today.year - 1, start.month, min(start.day, 28))
    return begin, date(begin.year + 1, begin.month, begin.day) - timedelta(days=1)


class Err(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.body = status, {"error": code, "message": message, **extra}


# ------------------------------------------------------------------ the system
class DentalSystem:
    def __init__(self, today: date | None = None):
        self.today = today or date.today()
        self.patients = json.loads(json.dumps(PATIENTS))
        self.claims = json.loads(json.dumps(CLAIMS))
        self.bookings: dict[str, dict[str, Any]] = {}
        self.next_patient, self.next_booking = 20001, 7001
        self.lock = threading.Lock()
        # Grace has a hygiene visit in Bristol's earliest slot, always under 48 hours away (Bristol closes only on Sundays), so
        # cancelling it shows the late fee; Tom has a check-up in Manchester about nine days out, so moving it is free
        now = datetime.now()
        soon = next(datetime.combine(d, datetime.strptime(t, "%H:%M").time())
                    for d in (self.today + timedelta(days=n) for n in range(0, 3)) if is_open("bristol", d)
                    for t in times("bristol", d, "hygiene") if datetime.combine(d, datetime.strptime(t, "%H:%M").time()) > now + timedelta(minutes=15))
        later = next(self.today + timedelta(days=n) for n in range(9, 16) if (self.today + timedelta(days=n)).weekday() < 5)
        self._book("OD-10822", slot_id("bristol", soon.date(), soon.strftime("%H:%M")), "hygiene")
        self._book("OD-10457", slot_id("manchester", later, "14:00"), "check_up")

    # appointments ------------------------------------------------
    def _taken(self) -> set[str]:
        return {b["slot_id"] for b in self.bookings.values() if b["status"] == "booked"}

    def slots(self, practice: str, appt: str, from_date: str, member: str | None) -> dict[str, Any]:
        p = practice_key(practice) or (self.patients.get(member or "", {}).get("practice"))
        if not p:
            raise Err(422, "practice_required", "Say which practice: Leeds, Manchester or Bristol.", practices=list(PRACTICES))
        a = key(appt, TYPE_ALIASES)
        if a not in APPOINTMENT_TYPES:
            raise Err(422, "invalid_appointment_type", "Unknown appointment type.", valid_types=list(APPOINTMENT_TYPES))
        if a == "sedation_consultation" and p not in SEDATION_PRACTICES:
            raise Err(422, "not_offered", "Sedation is offered at Oakhaven Leeds and Oakhaven Manchester only.")
        start = self.today if a == "emergency" else self.today + timedelta(days=1)
        if from_date:
            wanted = {"today": self.today, "tomorrow": self.today + timedelta(days=1)}.get(from_date.strip().lower())
            try:
                wanted = wanted or date.fromisoformat(from_date.strip()[:10])
            except ValueError:
                wanted = None
            if wanted and wanted > start:
                start = wanted
        taken, now, out = self._taken(), datetime.now(), []
        for n in range(0, 21):
            d = start + timedelta(days=n)
            if not is_open(p, d):
                continue
            for i, t in enumerate(times(p, d, a)):
                sid = slot_id(p, d, t)
                when = datetime.combine(d, datetime.strptime(t, "%H:%M").time())
                if sid in taken or (d == self.today and when <= now) or (a != "emergency" and (d.toordinal() + i) % 3 == 0):
                    continue  # booked, past, or already taken by other patients
                out.append({"slot_id": sid, "date": d.isoformat(), "weekday": d.strftime("%A"), "time": t})
            if len(out) >= 6 or (a == "emergency" and out):
                break
        minutes, price = APPOINTMENT_TYPES[a]
        return {"practice": PRACTICES[p]["name"], "appointment_type": a, "duration_minutes": minutes, "price_guide": price,
                "slots": out[:6]}

    def _book(self, member: str, sid: str, appt: str, notes: str = "") -> dict[str, Any]:
        parsed = parse_slot(sid)
        if not parsed:
            raise Err(422, "invalid_slot", "Use a slot_id from find_appointment_slots.")
        practice, when = parsed
        a = key(appt, TYPE_ALIASES)
        if a not in APPOINTMENT_TYPES:
            raise Err(422, "invalid_appointment_type", "Unknown appointment type.", valid_types=list(APPOINTMENT_TYPES))
        if sid in self._taken():
            raise Err(409, "slot_taken", "That slot has just been taken; find another.")
        ref = f"BK-{self.next_booking}"
        self.next_booking += 1
        minutes, price = APPOINTMENT_TYPES[a]
        self.bookings[ref] = {"booking_ref": ref, "patient": member, "slot_id": sid, "practice": practice, "appointment_type": a,
                              "date": when.date().isoformat(), "time": when.strftime("%H:%M"), "duration_minutes": minutes,
                              "price_guide": price, "notes": notes[:300], "status": "booked"}
        return self.bookings[ref]

    def _public(self, b: dict[str, Any]) -> dict[str, Any]:
        p = PRACTICES[b["practice"]]
        return {k: v for k, v in b.items() if k not in ("patient", "practice")} | {
            "practice": p["name"], "address": p["address"], "weekday": date.fromisoformat(b["date"]).strftime("%A")}

    def book(self, member: str, body: dict[str, Any]) -> dict[str, Any]:
        patient = self._patient(member)
        a = key(str(body.get("appointment_type", "")), TYPE_ALIASES)
        if patient.get("new") and a not in ("new_patient_exam", "emergency"):
            raise Err(422, "new_patient_exam_first", "New patients start with a new_patient_exam (or an emergency appointment).")
        parsed = parse_slot(str(body.get("slot_id", "")))
        if parsed and a == "sedation_consultation" and parsed[0] not in SEDATION_PRACTICES:
            raise Err(422, "not_offered", "Sedation is offered at Oakhaven Leeds and Oakhaven Manchester only.")
        with self.lock:
            b = self._book(member, str(body.get("slot_id", "")), a, str(body.get("notes") or ""))
        out = self._public(b) | {"reminder": "A text reminder is sent 48 hours before and on the morning of the appointment.",
                                 "cancellation_policy": "Free to cancel or move with at least 48 hours' notice; later than that the fee is £30 (£60 over 45 minutes)."}
        if a == "sedation_consultation":
            out["deposit"] = "No deposit for the consultation; sedation appointments need a £50 deposit."
        return out

    def mine(self, member: str) -> dict[str, Any]:
        self._patient(member)
        items = [self._public(b) for b in self.bookings.values() if b["patient"] == member and b["status"] == "booked"]
        return {"appointments": sorted(items, key=lambda b: (b["date"], b["time"]))}

    def _owned(self, member: str, ref: str) -> dict[str, Any]:
        b = self.bookings.get((ref or "").strip().upper())
        if not b or b["patient"] != member or b["status"] != "booked":
            raise Err(404, "booking_not_found", "No upcoming appointment with that reference for this patient.")
        return b

    def _late_fee(self, b: dict[str, Any]) -> int:
        start = datetime.fromisoformat(f"{b['date']}T{b['time']}")
        if start - datetime.now() >= timedelta(hours=48):
            return 0
        return 30 if b["duration_minutes"] <= 45 else 60

    def cancel(self, member: str, ref: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            b = self._owned(member, ref)
            fee = self._late_fee(b)
            b["status"], b["cancel_reason"] = "cancelled", str(body.get("reason") or "")[:200]
        return {"cancelled": True, "booking_ref": b["booking_ref"], "late_cancellation_fee": fee,
                "fee_note": "Less than 48 hours' notice: the late cancellation fee applies. The team can waive it once a year or for a documented illness."
                if fee else "Cancelled with at least 48 hours' notice: no charge."}

    def reschedule(self, member: str, ref: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            old = self._owned(member, ref)
            fee = self._late_fee(old)
            new = self._book(member, str(body.get("new_slot_id", "")), old["appointment_type"], old.get("notes", ""))
            old["status"], old["moved_to"] = "moved", new["booking_ref"]
        return self._public(new) | {"replaces": old["booking_ref"], "late_change_fee": fee}

    # patients ----------------------------------------------------
    def _patient(self, member: str | None) -> dict[str, Any]:
        p = self.patients.get(member or "")
        if not p:
            raise Err(401, "not_verified", "Verify the patient first.")
        return p

    def verify(self, body: dict[str, Any]) -> dict[str, Any]:
        ref = norm_patient(str(body.get("patient_id", "")))
        p = self.patients.get(ref)
        if not p or parse_dob(str(body.get("date_of_birth", ""))) != p["dob"]:
            return {"verified": False, "reason": "Patient ID and date of birth do not match our records."}
        return {"verified": True, "member_ref": ref, "first_name": p["first_name"], "home_practice": PRACTICES[p["practice"]]["name"]}

    def register(self, body: dict[str, Any]) -> dict[str, Any]:
        missing = [f for f in ("first_name", "last_name", "date_of_birth", "mobile") if not str(body.get(f) or "").strip()]
        if missing:
            raise Err(422, "missing_fields", "Ask the caller for: " + ", ".join(missing), missing=missing)
        dob = parse_dob(str(body["date_of_birth"]))
        if not dob:
            raise Err(422, "invalid_date_of_birth", "Give the date of birth as day, month and year.")
        practice = practice_key(str(body.get("preferred_practice", ""))) or "leeds"
        with self.lock:
            ref = f"OD-{self.next_patient}"
            self.next_patient += 1
            self.patients[ref] = {"first_name": str(body["first_name"]).strip()[:40], "last_name": str(body["last_name"]).strip()[:40],
                                  "dob": dob, "practice": practice, "new": True}
        return {"verified": True, "member_ref": ref, "patient_id": ref, "first_name": self.patients[ref]["first_name"],
                "home_practice": PRACTICES[practice]["name"], "next_step": "Book a new_patient_exam (40 minutes, £75)."}

    # cover, estimates, claims ------------------------------------
    def cover(self, member: str) -> dict[str, Any]:
        p = self._patient(member)
        out: dict[str, Any] = {"first_name": p["first_name"]}
        if ins := p.get("insurance"):
            start = date.fromisoformat(ins["start"])
            begin, end = benefit_year(start, self.today)
            cats = []
            for cat, (share, limit) in LEVELS[ins["level"]].items():
                used = ins["used"].get(cat, 0)
                waits = add_months(start, WAITING_MONTHS[cat])
                cats.append({"category": cat, "pays": f"{int(share * 100)}%", "annual_limit": limit, "used_this_year": used,
                             "remaining": max(limit - used, 0), "waiting_period_ends": waits.isoformat() if waits > self.today else None})
            out["insurance"] = {"product": "Oakhaven Dental Insurance", "level": ins["level"], "policy_start": ins["start"],
                                "benefit_year": {"from": begin.isoformat(), "to": end.isoformat()}, "categories": cats,
                                "major_cover": "not covered at Level 1" if ins["level"] == "Level 1" else ("includes implants" if ins["level"] == "Level 3" else "implants not covered"),
                                "accidental_injury": "covered from day one, up to £1,000 a year"}
        if cp := p.get("care_plan"):
            plan = CARE_PLANS[cp["plan"]]
            out["care_plan"] = {"product": "Oakhaven Care Plan", "plan": cp["plan"], "monthly": plan["monthly"],
                                "check_ups_left_this_year": plan["check_ups"] - cp["used"].get("check_ups", 0),
                                "hygiene_left_this_year": plan["hygiene"] - cp["used"].get("hygiene", 0),
                                "treatment_discount": f"{int(plan['discount'] * 100)}%", "emergency_fees_included": plan["emergency_included"]}
        if len(out) == 1:
            out["note"] = "No Oakhaven Care Plan or Oakhaven Dental Insurance on record: treatment is charged at the price list."
        return out

    def estimate(self, member: str, treatment: str) -> dict[str, Any]:
        p = self._patient(member)
        t = key(treatment, TREATMENT_ALIASES)
        if t == "root_canal":
            raise Err(422, "which_tooth", "Root canal prices depend on the tooth: front, premolar or molar.",
                      valid_treatments=["root_canal_front", "root_canal_premolar", "root_canal_molar"])
        if t not in TREATMENTS:
            raise Err(422, "unknown_treatment", "Unknown treatment.", valid_treatments=list(TREATMENTS))
        price, cat, from_price = TREATMENTS[t]
        out: dict[str, Any] = {"treatment": t, "price": price, "price_is_from": from_price, "category": cat}
        cost = float(price)
        if cp := p.get("care_plan"):
            plan = CARE_PLANS[cp["plan"]]
            included = (t == "check_up" and cp["used"].get("check_ups", 0) < plan["check_ups"]) or \
                       (t == "hygiene" and cp["used"].get("hygiene", 0) < plan["hygiene"]) or \
                       (t == "emergency_appointment" and plan["emergency_included"])
            discount = cost if included else round(cost * plan["discount"], 2)
            out["care_plan"] = {"plan": cp["plan"], "included_in_plan": included, "discount": discount}
            cost -= discount
        insurance_pays = 0.0
        if ins := p.get("insurance"):
            rules = LEVELS[ins["level"]]
            start = date.fromisoformat(ins["start"])
            info: dict[str, Any] = {"level": ins["level"]}
            if cat not in rules or (t == "implant" and ins["level"] != "Level 3"):
                info["covered"] = False
                info["reason"] = {"cosmetic": "Cosmetic treatment is not covered.", "sedation": "Sedation is not covered."}.get(
                    cat, f"{cat.capitalize()} treatment{' (implants)' if t == 'implant' else ''} is not covered at {ins['level']}.")
            elif (waits := add_months(start, WAITING_MONTHS[cat])) > self.today:
                info.update(covered=False, reason=f"{cat.capitalize()} treatment is in its waiting period until {waits.isoformat()}.",
                            waiting_period_ends=waits.isoformat())
            else:
                share, limit = rules[cat]
                remaining = max(limit - ins["used"].get(cat, 0), 0)
                insurance_pays = round(min(cost * share, remaining), 2)
                info.update(covered=True, pays=f"{int(share * 100)}%", remaining_limit=remaining)
            info["insurance_pays"] = insurance_pays
            out["insurance"] = info
        out["patient_pays"] = round(cost - insurance_pays, 2)
        if price > 300 and p.get("insurance"):
            out["advice"] = "Over £300: ask the dentist for a written treatment plan and send it for a pre-treatment estimate first."
        if from_price:
            out["note"] = "This is a 'from' price; the written treatment plan gives the final cost."
        return out

    def claim(self, member: str, claim_id: str) -> dict[str, Any]:
        self._patient(member)
        cid = "DC-" + re.sub(r"\D", "", claim_id or "")
        c = self.claims.get(cid)
        if not c or c["patient"] != member:
            raise Err(404, "claim_not_found", "No claim with that number for this patient. Claim numbers look like DC-5531.")
        return {"claim_id": cid} | {k: v for k, v in c.items() if k != "patient"}

    def claims_of(self, member: str) -> dict[str, Any]:
        self._patient(member)
        return {"claims": [{"claim_id": k, "treatment": c["treatment"], "treatment_date": c["treatment_date"], "status": c["status"]}
                           for k, c in self.claims.items() if c["patient"] == member]}


# what a dental insurance claim needs; the same answer the platform's retired claim-requirements mock gave (MOCK-14)
CLAIM_DOCUMENTS = {
    "claim_type": "dental",
    "documents": [{"document": "Itemised dental bill with procedure codes", "note": "From the dentist"},
                  {"document": "X-rays", "note": "Needed for crowns, bridges or implants"}],
    "where_to_send": "Upload them in your online account or email the claims team; the claim number must be on every page.",
}


# ------------------------------------------------------------------ HTTP
ROUTES: list[tuple[str, str, str]] = [
    ("POST", r"/dental/verify", "verify"), ("POST", r"/dental/patients", "register"),
    ("GET", r"/dental/slots", "slots"), ("POST", r"/dental/appointments", "book"), ("GET", r"/dental/appointments", "mine"),
    ("POST", r"/dental/appointments/(?P<ref>[^/]+)/cancel", "cancel"),
    ("POST", r"/dental/appointments/(?P<ref>[^/]+)/reschedule", "reschedule"),
    ("GET", r"/dental/cover", "cover"), ("GET", r"/dental/estimate", "estimate"),
    ("GET", r"/dental/claims", "claims_of"), ("GET", r"/dental/claims/(?P<claim_id>[^/]+)", "claim"), ("GET", r"/dental/health", "health"),
    ("GET", r"/dental/claim-documents", "claim_documents"),
]


def dispatch(system: DentalSystem, method: str, path: str, query: dict[str, str], body: dict[str, Any], member: str | None) -> tuple[int, Any]:
    for m, pattern, name in ROUTES:
        match = re.fullmatch(pattern, path.rstrip("/") or "/")
        if m != method or not match:
            continue
        g = match.groupdict()
        try:
            if name == "health":
                return 200, {"ok": True, "today": system.today.isoformat()}
            if name == "claim_documents":  # no patient needed: general information
                return 200, CLAIM_DOCUMENTS
            if name == "verify":
                return 200, system.verify(body)
            if name == "register":
                return 200, system.register(body)
            if name == "slots":
                return 200, system.slots(query.get("practice", ""), query.get("appointment_type", ""), query.get("from_date", ""), member)
            if name == "estimate":
                return 200, system.estimate(member or "", query.get("treatment", ""))
            if name in ("book",):
                return 200, system.book(member or "", body)
            if name in ("cancel", "reschedule"):
                return 200, getattr(system, name)(member or "", g["ref"], body)
            if name == "claim":
                return 200, system.claim(member or "", g["claim_id"])
            return 200, getattr(system, name)(member or "")
        except Err as exc:
            return exc.status, exc.body
    return 404, {"error": "not_found", "message": f"No route {method} {path}"}


def serve(port: int, system: DentalSystem | None = None) -> tuple[http.server.ThreadingHTTPServer, int, DentalSystem]:
    """Start the mock on 127.0.0.1:port (0 = any free port) in a daemon thread."""
    system = system or DentalSystem()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # quiet
            pass

        def _send(self, status: int, payload: Any) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self, method: str) -> None:
            parts = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            body: dict[str, Any] = {}
            if method == "POST":
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0)
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    return self._send(400, {"error": "invalid_json"})
                body = body if isinstance(body, dict) else {}
            self._send(*dispatch(system, method, parts.path, query, body, self.headers.get("X-Member-Ref")))

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1], system


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8766)
    srv, bound, _ = serve(ap.parse_args().port)
    print(f"Mock Oakhaven patient system on http://127.0.0.1:{bound}/dental/  (Ctrl+C stops)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
