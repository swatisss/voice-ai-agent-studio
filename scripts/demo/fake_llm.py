"""A scripted stand-in for every LLM role, so the demo walkthrough runs with no API keys and no cost.

Spec: /product/demo-walkthrough.md (Automated run, fake mode)

It is not a model. The agent plays each act's tool calls in order (verify, look up, act, one step per caller line where a
person would wait for a yes), answers knowledge questions with the sentences of the best search result that share the
most words with the question, hands over to another team when the request belongs to tools it does not have, ends the call
on a goodbye and escalates when the caller's words meet the agent's escalation rules. The simulated caller states its goal,
gives its details when asked and hangs up once answered. The judge passes every check but `outcome.goal_met` when the
answer does not cover the goal, and analysis, packets, memory and fix drafts are built from the transcript and evidence they
are given. Good for checking plumbing and the demo's flow; it says nothing about answer quality.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from voiceai.llm.gateway import FakeReply

STOP = set("a an the and or but if of to in on at for with by from is are was were be been am do does did i me my you your we our "
           "it its this that these those there what which who how much many can could would should will about any some please "
           "hi hello thanks thank yes no not get got while still already here from than just also".split())  # filler, never evidence of an answer
GENERIC = {"caller", "callers", "customer", "member", "members", "someone", "person", "specialist", "request", "wants", "asks",
           "policy", "plan", "health", "cover", "covered", "coverage", "claim", "claims", "insurance", "know", "want", "need",
           "help", "tell", "much", "northgate", "standard"}
ESC_IGNORE = {"underwriting", "decision", "refer_to_underwriter", "treatment", "change", "remove"}  # too common to trigger a hand-off alone
GOODBYE = re.compile(r"\b(bye|goodbye|that's (all|everything)|that is all|nothing else)\b", re.I)
HANDOFF_ASK = re.compile(r"\b(speak|talk) to (a|an|someone|a real) (person|human|agent)|\breal person\b|\bconnect me\b", re.I)
CLAIM_ID = re.compile(r"\bCL-\d{5}\b", re.I)
AUTH_ID = re.compile(r"\bPA-\d{6}\b", re.I)
MEMBER_ID = re.compile(r"\b(?:NGH-?)?(\d{6})\b")
DOB = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+\w")
MOBILE = re.compile(r"\b(07\d{3}\s?\d{6})\b")
CONDITION = re.compile(r"\b(knee|back|hip|shoulder|neck|joint) (pain|injury)\b", re.I)
YES = re.compile(r"\b(yes|yeah|please|go ahead|the first|that one|i confirm|confirm|agree)\b", re.I)
VERIFY_FIRST = re.compile(r"who's covered on my|my excess|been approved|has my claim|my direct debit|my (shoulder|knee|back) operation", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
SPOKEN_DATE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)? (" + "|".join(MONTHS) + r") (\d{4})\b", re.I)
CITIES = {"leeds": "LS1 4AP", "manchester": "M1 1AE", "bristol": "BS1 4DJ", "london": "EC1A 1BB"}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a": 1}
# requests that belong to another team: (caller's words, the tool that team has)
OTHER_TEAMS = [(r"direct debit|collection day|payment", "change_collection_day"), (r"\bquote\b", "create_quote"),
               (r"pre-?authori[sz]|specialist|consultant", "check_treatment_cover")]

SYNONYMS = {"newborn": "baby", "newborns": "baby", "babies": "baby", "infant": "baby", "born": "baby", "birth": "baby",
            "suspend": "pause", "hold": "pause", "overseas": "abroad", "away": "abroad", "premiums": "premium"}


def words(text: str) -> set[str]:
    found = (w for w in re.findall(r"[a-z0-9£,'-]+", text.lower()) if len(w) > 2 and w not in STOP)
    return {SYNONYMS.get(w, w) for w in found}


def sentences(text: str) -> list[str]:
    plain = re.sub(r"^#+ .*$", "", text, flags=re.M)
    return [s.strip().lstrip("-* ") for s in re.split(r"(?<=[.!?])\s+|\n+", plain) if len(s.strip()) > 15]  # list items read as sentences


def best_sentences(question: str, content: str, n: int = 2) -> str:
    """The sentences sharing the most question words; among equals, rare words count more (1 / sentences containing the word)."""
    q, pool = {w for w in words(question) if w not in GENERIC and len(w) > 3}, sentences(content)
    df = {w: sum(1 for s in pool if w in words(s)) for w in q}
    score = lambda s: (len(q & words(s)), sum(1 / df[w] for w in q & words(s) if df[w]))  # noqa: E731
    ranked = sorted(pool, key=lambda s: score(s), reverse=True)
    picked = [s for s in ranked[:n] if score(s)[0] > 0] or ranked[:1]
    return " ".join(picked)


def iso_dates(text: str) -> str:
    """'14 March 1984' becomes '1984-03-14', so spoken dates read like typed ones."""
    return SPOKEN_DATE.sub(lambda m: f"{m.group(3)}-{MONTHS.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}", text)


# ------------------------------------------------------------------ the conversation so far
@dataclass
class ToolUse:
    name: str
    args: dict[str, Any]
    result: dict[str, Any]
    at: int  # index of the assistant message that called it

    @property
    def ok(self) -> bool:
        return "error" not in self.result and self.result.get("verified") is not False


class Talk:
    """What the agent can see: the caller's lines and every tool it called, with results, in order."""

    def __init__(self, messages: list[dict[str, Any]]):
        self.system = str(messages[0].get("content") or "") if messages and messages[0].get("role") == "system" else ""
        self.uses: list[ToolUse] = []
        by_id: dict[str, ToolUse] = {}
        for i, m in enumerate(messages):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    use = ToolUse(fn.get("name", ""), args if isinstance(args, dict) else {}, {}, i)
                    self.uses.append(use)
                    by_id[tc.get("id", "")] = use
            elif m.get("role") == "tool" and m.get("tool_call_id") in by_id:
                try:
                    result = json.loads(m.get("content") or "{}")
                except ValueError:
                    result = {"text": m.get("content")}
                by_id[m["tool_call_id"]].result = result if isinstance(result, dict) else {"result": result}
        users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        self.last_user_at = users[-1] if users else -1
        self.caller_lines = [iso_dates(str(messages[i].get("content") or "")) for i in users]
        self.said = " ".join(self.caller_lines)
        self.last = self.caller_lines[-1] if self.caller_lines else ""

    def done(self, name: str) -> ToolUse | None:
        return next((u for u in reversed(self.uses) if u.name == name and u.ok), None)

    def tried_this_turn(self, name: str) -> bool:
        return any(u.name == name and u.at > self.last_user_at for u in self.uses)

    @property
    def verified(self) -> bool:  # this segment's tool result, or a verification carried over a transfer (the prompt says so)
        return any(u.name == "verify_member" and u.result.get("verified") is True for u in self.uses) \
            or bool(re.search(r"Identity verified: yes", self.system))

    def dates(self) -> list[str]:
        return DOB.findall(self.said)


# ------------------------------------------------------------------ Northgate tool chains
@dataclass
class Step:
    tool: str
    args: Callable[[Talk], dict[str, Any] | None]  # None: not ready (a detail is missing)
    wait: bool = False  # needs a new caller line after the previous step
    ask: str = ""  # what to ask when a detail is missing


def _policy_id(t: Talk) -> str | None:
    found = t.done("get_member_policies")
    rows = (found.result.get("policies") if found else None) or []
    return next((r["policy_id"] for r in rows if r.get("type") == "health"), rows[0]["policy_id"] if rows else None)


def _condition(t: Talk) -> str | None:
    m = CONDITION.search(t.said)
    return m.group(0).lower() if m else None


def _postcode(t: Talk) -> str | None:
    m = POSTCODE.search(t.said.upper())
    if m:
        return m.group(1)
    return next((code for city, code in CITIES.items() if re.search(rf"\b{city}\b", t.said, re.I)), None)


def _symptoms_started(t: Talk) -> str | None:
    m = re.search(r"(?:started|began|since)\D{0,12}(\d{4}-\d{2}-\d{2})", t.said, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\bfor (\w+) weeks?\b", t.said, re.I)
    if m:
        n = NUMBERS.get(m.group(1).lower()) or (int(m.group(1)) if m.group(1).isdigit() else 2)
        return (date.today() - timedelta(weeks=n)).isoformat()
    return None


def _people(t: Talk) -> list[dict[str, Any]]:
    dobs = t.dates()
    named = re.findall(r"\b([A-Z][a-z]+ [A-Z][a-z]+),? (?:was )?born", t.said)
    smoker = bool(re.search(r"\bI smoke\b", t.said, re.I))
    people = []
    for i, dob in enumerate(dobs[:6]):
        people.append({"name": named[i] if i < len(named) else f"Person {i + 1}", "date_of_birth": dob,
                       "smoker": smoker and i == 0, "relationship": "policyholder" if i == 0 else "partner" if i == 1 else "child"})
    return people


def _quote(t: Talk) -> dict[str, Any] | None:
    people, postcode = _people(t), _postcode(t)
    return {"people": people, "postcode": postcode} if people and postcode and POSTCODE.search(t.said.upper()) else None


def _price(t: Talk) -> dict[str, Any] | None:
    m = re.search(r"\b(essentials|balanced|complete)\b", t.last, re.I)
    if not m:
        return None
    add_ons = [key for key, pattern in (("dental_optical", r"dental|optical"), ("therapies_plus", r"therap"), ("travel_cover", r"travel"))
               if re.search(pattern, t.last, re.I)]
    return {"quote_id": t.done("create_quote").result["quote_id"], "package": m.group(1).lower(), "add_ons": add_ons}


def _underwriting(t: Talk) -> dict[str, Any] | None:
    m = re.search(r"\b(moratorium|full medical|switch)", t.last, re.I)
    if not m:
        return None
    method = m.group(1).lower().replace(" ", "_")
    out: dict[str, Any] = {"quote_id": t.done("create_quote").result["quote_id"], "method": method}
    if method == "full_medical":
        mine = re.findall(r"\bI had (\w+)", t.last)
        people = t.done("create_quote").result.get("people") or [{}]
        out["answers"] = [{"person": p.get("name") or i + 1, "conditions": mine if i == 0 else []} for i, p in enumerate(people)]
    return out


def _application(t: Talk) -> dict[str, Any] | None:
    quote, uw = t.done("create_quote"), t.done("assess_underwriting")
    confirmed = re.search(r"key facts", t.last, re.I) and re.search(r"declaration", t.last, re.I) and YES.search(t.last)
    email, mobile = EMAIL.search(t.said), MOBILE.search(t.said)
    if not (quote and uw and confirmed and email and mobile):
        return None
    me = re.search(r"\b([A-Z][a-z]+) ([A-Z][a-z]+),? (?:was )?born", t.said)
    address = re.search(r"address(?: is)? ([^.]+)", t.said, re.I)
    return {"quote_id": quote.result["quote_id"], "underwriting_id": uw.result["underwriting_id"],
            "policyholder": {"first_name": me.group(1) if me else "Alex", "last_name": me.group(2) if me else "Morgan",
                             "email": email.group(0), "mobile": mobile.group(1), "address": address.group(1).strip() if address else "Address on file"},
            "documents_by": "email", "payment_link_by": "email" if re.search(r"link by email|email (me )?the (direct debit )?link", t.said, re.I) else "sms",
            "key_facts_confirmed": True, "declaration_confirmed": True}


def _first(t: Talk, tool: str, key: str, field: str) -> Any:  # noqa: ANN401
    found = t.done(tool)
    return ((found.result.get(key) if found else None) or [{}])[0].get(field)


def _chain(t: Talk, names: set[str]) -> list[Step] | None:
    """The chain the caller's words ask for, among the agent's tools."""
    if "create_quote" in names and re.search(r"\bquote\b", t.said, re.I):
        return [
            Step("create_quote", _quote, ask="Happy to help. For each person, what's their name and date of birth, and does anyone smoke? "
                                             "And what's your postcode?"),
            Step("price_quote", _price, wait=True),
            Step("assess_underwriting", _underwriting, wait=True),
            Step("create_policy", _application, wait=True,
                 ask="Before I set up the policy I need your email, mobile and address, and a clear yes that you've heard the key facts "
                     "and that you agree to the declaration."),
        ]
    if "check_treatment_cover" in names and _condition(t):
        return [
            Step("get_member_policies", lambda t: {}),
            Step("check_treatment_cover", lambda t: {"policy_id": _policy_id(t), "condition": _condition(t), "treatment": "consultation"}),
            Step("find_specialists", lambda t: {"condition": _condition(t), "policy_id": _policy_id(t), "postcode": _postcode(t)}
                 if t.done("check_treatment_cover").result.get("covered") and _postcode(t) else None, wait=True, ask="Where are you, roughly?"),
            Step("create_pre_authorisation", lambda t: {
                "policy_id": _policy_id(t), "condition": _condition(t), "treatment": "consultation", "symptoms_started": _symptoms_started(t),
                "referral": "direct_access" if t.done("check_treatment_cover").result.get("direct_access_category") else "open_referral",
                "specialist_id": _first(t, "find_specialists", "specialists", "specialist_id")}
                 if _symptoms_started(t) and YES.search(t.last) else None, wait=True, ask="Which specialist would you like, and when did it start?"),
        ]
    if "get_pre_authorisation" in names and re.search(r"approved|pre-?authori[sz]|operation", t.said, re.I):
        return [Step("get_pre_authorisation", lambda t: {"auth_id": AUTH_ID.search(t.said).group(0).upper()} if AUTH_ID.search(t.said) else None,
                     ask="What's the pre-authorisation code? It starts with PA.")]
    if "change_collection_day" in names and re.search(r"collection day|move my direct debit|direct debit to the", t.said, re.I):
        day = re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", t.said)
        return [Step("get_member_policies", lambda t: {}),
                Step("change_collection_day", lambda t: {"policy_id": _policy_id(t), "day": int(day.group(1))} if day else None,
                     ask="Which day of the month would you like?")]
    if "get_payments" in names and re.search(r"direct debit|missed|payment|bounced", t.said, re.I):
        return [
            Step("get_member_policies", lambda t: {}),
            Step("get_payments", lambda t: {"policy_id": _policy_id(t)}),
            Step("retry_missed_payment", lambda t: {"policy_id": _policy_id(t)}
                 if t.done("get_payments").result.get("status") == "missed" and re.search(r"\byes\b|again", t.last, re.I) else None, wait=True),
            Step("send_secure_link", lambda t: {"purpose": "change_bank_details", "channel": "sms", "policy_id": _policy_id(t)}
                 if re.search(r"changed banks?|new bank|bank details", t.last, re.I) else None, wait=True),
        ]
    if "book_gp_appointment" in names and re.search(r"\bGP\b", t.said):
        patient = re.search(r"\bCan ([A-Z][a-z]+) see", t.said)
        fmt = re.search(r"\b(video|phone)\b", t.said, re.I)
        return [
            Step("get_gp_slots", lambda t: {"type": "gp", **({"format": fmt.group(1).lower()} if fmt else {})}),
            Step("book_gp_appointment", lambda t: {"slot_id": _first(t, "get_gp_slots", "slots", "slot_id"),
                                                   "reason": "GP appointment" + (f" for {patient.group(1)}" if patient else ""),
                                                   **({"patient_name": patient.group(1)} if patient else {})}
                 if YES.search(t.last) else None, wait=True),
        ]
    if "get_policy_details" in names and re.search(r"who's covered|my excess", t.said, re.I):
        return [Step("get_member_policies", lambda t: {}), Step("get_policy_details", lambda t: {"policy_id": _policy_id(t)})]
    return None


NEEDS_VERIFICATION = {"get_member_policies", "get_policy_details", "get_payments", "retry_missed_payment", "send_secure_link",
                      "change_collection_day", "get_gp_slots", "book_gp_appointment", "check_treatment_cover",
                      "create_pre_authorisation", "get_pre_authorisation", "get_claim_status"}
ASK_VERIFY = "I can help with that. First, what's your membership number and your date of birth?"


def next_step(t: Talk, names: set[str]) -> tuple[str, dict[str, Any]] | str | None:
    """The next tool call, a question for the caller (a str), or None to answer in words."""
    if "verify_member" in names and not t.verified and not t.tried_this_turn("verify_member"):
        dob = DOB.search(t.last)
        member = MEMBER_ID.search(t.said.replace(dob.group(1), "") if dob else t.said)
        if dob:  # an identified caller verifies with the date of birth only (flow A)
            return "verify_member", {"date_of_birth": dob.group(1), **({"member_id": f"NGH-{member.group(1)}"} if member else {})}
    chain = _chain(t, names)
    if not chain:
        return None
    previous_this_turn = False
    for step in chain:
        if t.done(step.tool):
            previous_this_turn = t.done(step.tool).at > t.last_user_at
            continue
        if step.tool not in names or t.tried_this_turn(step.tool):
            return None  # it failed this turn: say why
        if step.tool in NEEDS_VERIFICATION and "verify_member" in names and not t.verified:
            return None if t.tried_this_turn("verify_member") else ASK_VERIFY
        if step.wait and previous_this_turn:
            return None  # tell the caller, then wait for their answer
        args = step.args(t)
        if args is None:
            return step.ask or None
        return step.tool, {k: v for k, v in args.items() if v is not None}
    return None


# ------------------------------------------------------------------ answers in words
def _money(v: Any) -> str:  # noqa: ANN401
    try:
        return f"£{float(v):,.2f}".replace(".00", "")
    except (TypeError, ValueError):
        return str(v)


ANYTHING_ELSE = " Is there anything else I can help with?"


def _answer_from_tool(name: str, result: dict[str, Any], question: str) -> FakeReply:
    r = result
    if r.get("say"):
        return FakeReply(text=str(r["say"]))
    if r.get("error"):
        detail = r.get("detail") or ""
        try:
            detail = json.loads(detail).get("detail", detail) if isinstance(detail, str) and detail.startswith("{") else detail
        except ValueError:
            pass
        return FakeReply(text=f"Sorry, I couldn't do that: {detail or r['error']}.")
    if name == "search_knowledge":
        if r.get("no_answer") or not r.get("results"):
            return FakeReply(text="I don't have approved information on that. Would you like me to connect you with a specialist?")
        content = "\n".join(x.get("content", "") for x in r["results"])  # the best sentences across every result
        return FakeReply(text=best_sentences(question, content) + ANYTHING_ELSE)
    if name == "verify_member":
        return FakeReply(text=f"Thank you, {r.get('first_name', '')}, you're verified. How can I help?")
    if name == "get_policy_details":
        cover = r.get("cover") or {}
        return FakeReply(text=f"Your {r.get('product')} policy covers {', '.join(r.get('insured_persons') or [])}. The excess is "
                              f"{_money(cover.get('excess'))}, outpatient {cover.get('outpatient_limit')}, hospital list {cover.get('hospital_list')}." + ANYTHING_ELSE)
    if name == "get_payments":
        if r.get("status") == "missed":
            return FakeReply(text=f"Your Direct Debit of {_money(r.get('missed_amount'))} was missed, so cover is suspended until it is paid by "
                                  f"{r.get('reinstate_by')}. I can collect it again in three working days. Shall I do that?")
        return FakeReply(text=f"Your payments are up to date: {_money(r.get('monthly_amount'))} a month, next collection {r.get('next_collection_date')}." + ANYTHING_ELSE)
    if name == "retry_missed_payment":
        return FakeReply(text=f"Done: we'll collect {_money(r.get('amount'))} on {r.get('collect_on')}, reference {r.get('reference')}. "
                              f"{r.get('next_step', '')}" + ANYTHING_ELSE)
    if name == "send_secure_link":
        return FakeReply(text=f"I've sent a secure link to {r.get('sent_to')}: {r.get('purpose')}. It works for {r.get('expires_in_hours')} hours, "
                              "so you never need to read bank details out on a call." + ANYTHING_ELSE)
    if name == "change_collection_day":
        return FakeReply(text=f"Done: your Direct Debit now comes out on day {r.get('collection_day')}, next on {r.get('next_collection_date')}. "
                              f"{r.get('note', '')}" + ANYTHING_ELSE)
    if name == "get_gp_slots":
        slots = "; ".join(f"{s['date']} at {s['time']} by {s['format']}" for s in (r.get("slots") or [])[:3])
        return FakeReply(text=f"I can offer {slots}. Shall I book the first one?" if slots else "There are no free appointments right now." + ANYTHING_ELSE)
    if name == "book_gp_appointment":
        return FakeReply(text=f"Booked for {r.get('patient')}: {r.get('date')} at {r.get('time')} by {r.get('format')}, reference {r.get('booking_id')}. "
                              f"{r.get('how_to_join', '')}" + ANYTHING_ELSE)
    if name == "check_treatment_cover":
        if not r.get("covered"):
            return FakeReply(text=f"I'm sorry, that isn't covered: {r.get('reason')}" + ANYTHING_ELSE)
        return FakeReply(text=f"Good news: {r.get('condition')} is covered on policy {r.get('policy_id')}. {r.get('next_step', '')} "
                              "Shall I find a specialist near you? Where are you?")
    if name == "find_specialists":
        rows = r.get("specialists") or []
        if not rows:
            return FakeReply(text=str(r.get("note") or "I couldn't find a recognised specialist.") + ANYTHING_ELSE)
        listed = "; ".join(f"{i}. {s['name']} at {s['hospital']}, first available {s['first_available']}" for i, s in enumerate(rows, 1))
        return FakeReply(text=f"Here are recognised specialists: {listed}. Which would you like?")
    if name == "create_pre_authorisation":
        return FakeReply(text=f"Your pre-authorisation code is {r.get('pre_auth_code')}, status {r.get('status')}"
                              + (f", with {r['specialist']}" if r.get("specialist") else "") + f". {r.get('next_step', '')}" + ANYTHING_ELSE)
    if name == "get_pre_authorisation":
        return FakeReply(text=f"Pre-authorisation {r.get('auth_id') or r.get('pre_auth_code', '')} is {r.get('status')}. {r.get('notes', '')}" + ANYTHING_ELSE)
    if name == "create_quote":
        packs = "; ".join(f"{p['label']} {_money(p['monthly_total'])} a month" for p in r.get("packages", []))
        return FakeReply(text=f"Your quote {r.get('quote_id')}: {packs}. Which cover would you like?")
    if name == "price_quote":
        return FakeReply(text=f"That cover is {_money(r.get('monthly_total'))} a month, {_money(r.get('annual_total'))} a year. "
                              "Which underwriting would you like: moratorium, full medical underwriting, or switching from another insurer?")
    if name == "assess_underwriting":
        if r.get("decision") == "refer_to_underwriter":
            return FakeReply(text="An underwriter needs to look at this before cover can start.", tool_calls=[
                ("escalate_to_human", {"reason_category": "policy_required", "reason_detail": "Referred to an underwriter"})])
        excluded = [x for p in r.get("people") or [] for x in p.get("exclusions") or []]
        return FakeReply(text=f"With {str(r.get('method', '')).replace('_', ' ')} underwriting the price is {_money(r.get('monthly_total'))} a month"
                              + (f", excluding {'; '.join(excluded)}" if excluded else "") + ". Would you like to join?")
    if name == "create_policy":
        return FakeReply(text=f"You're covered: policy {r.get('policy_id')}, membership number {r.get('membership_number')}, starting {r.get('start_date')}. "
                              f"The Direct Debit link is on its way to {r.get('direct_debit_link_sent_to')}, and you can cancel within 21 days, "
                              f"until {r.get('cooling_off_ends')}." + ANYTHING_ELSE)
    if name == "get_claim_status" and r.get("status"):
        return FakeReply(text=f"Claim {r.get('claim_id', '')} is {r['status']}." + ANYTHING_ELSE)
    return FakeReply(text="Thanks, that's done." + ANYTHING_ELSE)


# ------------------------------------------------------------------ the agent (role realtime)
def _escalation_rules(system: str) -> list[str]:
    block = system.split("# Escalate by calling escalate_to_human when", 1)[-1].split("After calling", 1)[0]
    return [line[2:].strip() for line in block.splitlines() if line.startswith("- ")]


def _stem(w: str) -> str:
    return w[:-1] if w.endswith("s") and len(w) > 4 else w


def _meets_rule(question: str, system: str) -> bool:
    asked = {_stem(w) for w in words(question)}
    for rule in _escalation_rules(system)[1:-1]:  # the first and last lines are the platform's own
        keys = {_stem(w) for w in words(rule) if len(w) > 5 and w not in GENERIC and w not in ESC_IGNORE}
        if asked & keys:
            return True
    return False


def _other_team(question: str, names: set[str]) -> bool:
    return "transfer_to_agent" in names and any(re.search(p, question, re.I) and tool not in names for p, tool in OTHER_TEAMS)


def agent(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> FakeReply:
    system = str(messages[0].get("content") or "") if messages else ""
    names = {t.get("function", {}).get("name") or t.get("name") for t in tools or []}
    t = Talk(messages)
    question = t.last
    last = messages[-1] if messages else {}
    if last.get("role") == "tool":  # carry on with the chain, or answer from the tool that just returned
        step = next_step(t, names)
        if isinstance(step, tuple):
            return FakeReply(tool_calls=[step])
        use = t.uses[-1] if t.uses else ToolUse("", {}, {}, 0)
        reply = _answer_from_tool(use.name, use.result, question)
        if isinstance(step, str) and use.name == "verify_member" and use.ok:
            reply = FakeReply(text=reply.text.replace("How can I help?", step))
        return reply
    if GOODBYE.search(question):
        return FakeReply(text="Thank you for calling. Goodbye!", tool_calls=[("end_call", {"summary": "Answered the caller's questions."})])
    if HANDOFF_ASK.search(question) or _meets_rule(question, system):
        return FakeReply(tool_calls=[("escalate_to_human", {"reason_category": "policy_required", "reason_detail": question[:200]})])
    if _other_team(question, names):
        return FakeReply(tool_calls=[("transfer_to_agent", {"reason": question[:200], "summary": question[:300]})])
    if "get_claim_status" in names and CLAIM_ID.search(question):  # the runtime's gate decides, not this stand-in
        return FakeReply(tool_calls=[("get_claim_status", {"claim_id": CLAIM_ID.search(question).group(0).upper()})])
    step = next_step(t, names)
    if isinstance(step, tuple):
        return FakeReply(tool_calls=[step])
    if isinstance(step, str) and "?" not in question or step == ASK_VERIFY:
        return FakeReply(text=step)
    if "verify_member" in names and VERIFY_FIRST.search(question) and not t.verified:
        return FakeReply(text=ASK_VERIFY)
    if "promise" in question.lower():
        return FakeReply(text="I can't promise that a claim will be paid; claims are assessed against the policy and the invoices you send.")
    return FakeReply(tool_calls=[("search_knowledge", {"query": question[:200]})])


# ------------------------------------------------------------------ the simulated caller (role simulator)
def caller(prompt: str) -> str:
    goal = re.search(r"Your goal: (.+)", prompt)
    details = re.search(r"Your details \(share only when asked\): (.+)", prompt)
    details_text = details.group(1) if details else ""
    transcript = prompt.split("Conversation so far:", 1)[-1]
    turns = transcript.count("\nCaller:")
    agent_lines = re.findall(r"^Agent: (.*)$", transcript, flags=re.M)
    if turns == 0 and goal:
        text = goal.group(1).strip()
        for a, b in ((r"\bYou are\b", "I am"), (r"\bYou have\b", "I have"), (r"\bYou want\b", "I want"), (r"\bYou\b", "I"),
                     (r"\byou\b", "I"), (r"\bYour\b", "My"), (r"\byour\b", "my")):
            text = re.sub(a, b, text)
        return "Hi. " + text
    last = agent_lines[-1] if agent_lines else ""
    member, dob = MEMBER_ID.search(details_text), DOB.search(details_text)
    if re.search(r"membership number|date of birth", last, re.I) and member and dob and turns < 4:
        return f"My membership number is NGH-{member.group(1)} and my date of birth is {dob.group(1)}."
    if re.search(r"don't have approved information|can't help|cannot help", last, re.I):
        return "Yes, please connect me with a specialist."  # not answered: a real caller takes the offer
    if turns >= 4 or "?" not in last or re.search(r"anything else|connect you|specialist", last, re.I):
        return "[HANGUP]"  # answered: a real caller says goodbye instead of inventing new questions
    if re.search(r"shall i|would you like me", last, re.I):
        return "Yes, please."
    return "I'd rather not say. Thanks anyway. [HANGUP]"


# ------------------------------------------------------------------ JSON roles, by output schema
def _first_caller_line(prompt: str) -> str:
    m = re.search(r"(?:Caller|User|caller): (.+)", prompt)
    return m.group(1).strip()[:200] if m else "The caller had a question."


def goal_answered(prompt: str) -> bool:
    """The agent's lines share a distinctive word with the caller's goal and never say the answer is missing."""
    goal = re.search(r"Caller goal: (.+)", prompt)
    said = " ".join(re.findall(r"Agent: (.+)", prompt))
    if not goal or re.search(r"don't have approved information", said, re.I):
        return False
    distinctive = {w for w in words(goal.group(1)) if w not in GENERIC and len(w) > 3}
    return bool(distinctive & words(said))


INTENTS = (("add_dependent_newborn", r"\b(baby|newborn|born)\b"), ("pause_abroad", r"\b(pause|on hold|suspend)\b"),
           ("prior_auth_status", r"pre-?authori[sz]ation|been approved"), ("claim_dispute", r"\bdispute|declined"),
           ("complaint", r"\bcomplain"), ("cancellation", r"\bcancel"), ("payment_question", r"direct debit|payment"),
           ("quote", r"\bquote\b"), ("gp_booking", r"\bGP\b"))


def _intent(text: str) -> str:
    return next((name for name, pattern in INTENTS if re.search(pattern, text, re.I)), "coverage_question")


def json_reply(role: str, prompt: str, schema: str) -> dict[str, Any]:
    escalated = "escalate_to_human" in prompt or "Escalated" in prompt
    goal = _first_caller_line(prompt)
    if schema == "JudgeOut":
        block = prompt.split("Checks:\n", 1)[1].split("\n\nReturn JSON", 1)[0] if "Checks:\n" in prompt else ""
        keys = [line.split(":", 1)[0] for line in block.splitlines() if line and line != "(none)"]
        checks = {k: {"verdict": "pass", "reason": "Scripted judge: passes every check.", "seqs": []} for k in keys}
        met = escalated or goal_answered(prompt)
        if "outcome.goal_met" in checks and not met:  # test runs and fix evaluations decide on this check
            checks["outcome.goal_met"] = {"verdict": "fail", "reason": "Scripted judge: the answer does not cover the goal.", "seqs": []}
        return {"outcome": "escalated" if escalated else "resolved", "goal_met": met, "grounded": True,
                "policy_violations": [], "notes": "Scripted judge (demo fake mode).", "checks": checks}
    if schema == "AnalysisOut":
        # a specialist answered what the agent could not: the answer was missing from the knowledge, and the gap is
        # described by that answer, as a real analyst would summarise it (so paraphrased questions cluster together)
        note = re.search(r"human resolution note: ([^\n]+)", prompt)
        gap = "no approved information" in prompt.lower() or bool(escalated and note)
        safety = bool(re.search(r"\b999\b|emergency|chest pain", prompt, re.I))
        root = ("missing_knowledge" if gap else "safety" if safety else "policy_required" if re.search(r"complain|cancel|dispute", goal, re.I)
                else "caller_requested") if escalated else "none"
        summary = f"No approved answer; a specialist explained: {note.group(1).strip()}" if note else goal
        return {"outcome": "escalated" if escalated else "resolved", "intent": _intent(goal), "root_cause": root,
                "gap_summary": summary if gap else "", "caller_goal": goal, "resolution_summary": "Scripted analysis (demo fake mode).",
                "sentiment_start": "neutral", "sentiment_end": "neutral"}
    if schema == "Packet":
        category = "safety" if re.search(r"\b999\b|emergency", prompt, re.I) else "policy_required"
        claim = CLAIM_ID.search(prompt)
        return {"summary": f"The caller said: {goal}", "intent": _intent(goal), "entities": {"claim_id": claim.group(0)} if claim else {},
                "already_tried": [], "escalation_reason": {"category": category, "detail": goal},
                "suggested_next_action": "Call the caller back and help with their request.", "caller_verified": False}
    if schema == "MemoryExtractOut":
        return {"episode": f"Called about: {goal}", "facts": []}
    if schema == "MemoryDecisionOut":
        return {"action": "NOOP", "reason": "Scripted (demo fake mode)."}
    if schema == "ClusterName":
        gaps = prompt.split("Root causes:", 1)[0].split("escalated to humans:", 1)[-1]  # not the prompt's own example name
        if re.search(r"\b(baby|newborn)\b", gaps, re.I):
            return {"name": "Adding a newborn to the policy", "description": "Callers want to know how and when to add a new baby to their health insurance."}
        if re.search(r"\b(pause|abroad|on hold)\b", gaps, re.I):
            return {"name": "Pausing a policy while abroad", "description": "Callers working or living abroad ask whether they can pause their policy."}
        return {"name": "Recurring question", "description": "Callers ask about the same topic."}
    if schema == "FixDraft":
        notes = list(dict.fromkeys(m.strip() for m in re.findall(r"Specialist: ([^|\n]+)", prompt) if "(no note)" not in m))
        notes += [m.strip() for m in re.findall(r"Reviewer's answer for all of these callers: (.+)", prompt)]  # CP-0032
        title = re.search(r"Cluster: (.+)", prompt)
        name = re.split(r" [—-] ", title.group(1).strip())[0] if title else "Answer to a recurring question"
        body = "\n".join(f"- {n}" for n in notes[:8]) or "- Specialists answered this question; see the evidence."
        return {"kind": "knowledge_article", "title": name, "rationale": "Built from the specialists' resolution notes (demo fake mode).",
                "article": {"title": name, "content_markdown": f"# {name}\n\n{body}\n"}}
    if schema == "Utterances":  # the agent's own use-case examples, as a real model would paraphrase them
        examples = list(dict.fromkeys(re.findall(r'e\.g\. "([^"]+)"', prompt)))
        return {"utterances": examples[:20] or ["I have a question about my policy.", "Can you help me with my cover?"]}
    if schema == "Question":
        return {"question": "Could you tell me a little more about what you need?"}
    if schema == "TurnVerdictOut":
        return {"complete": True}
    return {}


def responder(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:  # noqa: ANN401
    """The gateway's fake responder for streamed roles (the agent and the simulated caller)."""
    if role == "simulator":
        return caller(str(messages[-1].get("content") or ""))
    return agent(messages, tools)
