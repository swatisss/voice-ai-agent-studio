#!/usr/bin/env python3
"""Run the demo walkthrough end to end against a running stack and write a report.

Spec: /product/demo-walkthrough.md

    python scripts/demo_walkthrough.py --learning          # default: fake mode, no API keys, no cost, about 30 s
    python scripts/dev.py                                  # in another terminal, for a live run against the stack on :8000
    python scripts/demo_walkthrough.py --live              # REAL LLM calls on your keys (costs money): build, call, score, test
    python scripts/demo_walkthrough.py --live --learning   # also replays 72 simulated calls for the newborn fix (about 6 min)
    python scripts/demo_walkthrough.py --serve-site        # only host the demo website, for the manual walkthrough

Fake mode starts its own throwaway API with a scripted stand-in for every LLM role (scripts/demo/fake_llm.py) and the
local embedding model, on a fresh seeded database, and stops it afterwards.

Every step drives the same REST API the web app uses (/api/rest-api.md), so the run shows
exactly what a builder sees. The demo agent lives in the sandbox business unit and is
updated in place on every run (a new version each time). Checks marked with a change
proposal are known gaps until that CP is implemented: they are reported, not failed.

Exit code: 0 when every core check passed, 1 otherwise. Stdlib only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "scripts" / "demo"
SITE_DIR = DEMO_DIR / "safetrip-site"
REPORT_DIR = ROOT / "apps" / "api" / "data" / "demo-runs"
API_DIR = ROOT / "apps" / "api"

AGENT_NAME = "Travel Cover Helpdesk"
AGENT_DESCRIPTION = ("Answers travellers' questions about what their travel insurance covers, "
                     "how to make a claim while abroad, and trip cancellation rules.")
POLICY_TITLE = "SafeTrip travel policy - key benefits"
TOOL = {
    "name": "get_claim_documents",
    "description": "Look up which documents a traveller must send for a claim type.",
    "method": "GET",
    "url": "/mock/insurance/claims/requirements",
    "parameters": {"type": "object", "properties": {"claim_type": {
        "type": "string", "enum": ["outpatient", "urgent_care", "inpatient", "dental"],
        "description": "outpatient for a doctor visit, urgent_care, inpatient for a hospital stay, or dental"}},
        "required": ["claim_type"]},
    "requires_verification": False, "is_verification": False, "timeout_s": 8,
}
SKILL = {
    "name": "Help a traveller start a claim",
    "description": "The caller wants to make a claim or asks what paperwork they need",
    "instructions": ("1. Ask what happened and pick the claim type: outpatient (doctor visit), urgent_care, "
                     "inpatient (hospital stay) or dental.\n2. Look up the required documents with "
                     "get_claim_documents and read them out.\n3. Remind them to send everything within "
                     "30 days of returning home."),
    "required_tools": ["get_claim_documents"],
    "escalate_when": "",
}
POLICY = {
    "rules": ["Always mention the $100 excess whenever you talk about a medical claim."],
    "never": ["Never promise that a claim will be approved or paid."],
    "escalate_when": ["The caller or someone travelling with them is in hospital abroad right now."],
}
# An empty caller profile means "not a member" to the simulated caller, who then asks how to join and
# accepts a specialist; the profile says these callers already hold a policy. The resolved scenarios are
# known gaps until roadmap R9: once answered, the simulated caller invents follow-up questions the knowledge
# does not cover and accepts the specialist the agent then offers (/product/roadmap.md).
POLICYHOLDER = {"name": "Alex Morgan", "policy": "SafeTrip Standard, bought before the trip"}
SCENARIOS = [
    {"name": "Lost baggage limit", "expected": "resolved", "caller_profile": POLICYHOLDER, "known": "R9",
     "caller_goal": "Your suitcase never arrived after a flight to Rome. You want to know how much SafeTrip pays for lost baggage."},
    {"name": "Stolen phone cover", "expected": "resolved", "caller_profile": POLICYHOLDER, "known": "R9",
     "caller_goal": "Your phone was stolen on holiday. You want to know how much SafeTrip pays and what you need for the claim."},
    {"name": "Do-not-travel country cover", "expected": "resolved", "caller_profile": POLICYHOLDER, "known": "R9",
     "caller_goal": "You are travelling next month to a country with a government do-not-travel warning and want to know if your SafeTrip policy still covers you there."},
    {"name": "Hospital abroad", "expected": "escalated", "caller_profile": POLICYHOLDER,
     "caller_goal": "Your husband was admitted to hospital in Lisbon an hour ago. You need urgent help with the hospital bill."},
]


# ------------------------------------------------------------------ report
@dataclass
class Check:
    step: str
    name: str
    ok: bool | None          # None: information only
    detail: str = ""
    known: str | None = None  # CP id when this is a known gap until that CP ships
    model: bool = False       # the outcome depends on the model, so a pass may only mean the gap did not show

    @property
    def label(self) -> str:
        if self.ok is None:
            return "INFO"
        if self.ok:
            if not self.known:
                return "PASS"
            return "PASS (not hit)" if self.model else "PASS (fixed)"
        return f"KNOWN ({self.known})" if self.known else "FAIL"


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)

    def add(self, step: str, name: str, ok: bool | None, detail: str = "", known: str | None = None, model: bool = False) -> bool:
        c = Check(step, name, ok, detail, known, model)
        self.checks.append(c)
        print(f"  [{c.label:>17}] {name}" + (f" - {detail}" if detail else ""), flush=True)
        return bool(ok)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.ok is False and not c.known]

    def markdown(self, started: datetime, args: argparse.Namespace) -> str:
        lines = [f"# Demo walkthrough run {started:%Y-%m-%d %H:%M}", "",
                 f"API `{args.api}`, business unit `{args.tenant}`" + (", with self-learning" if args.learning else ""),
                 "" if not args.fake else "\n**Fake mode**: scripted fake LLM, no API keys, no model calls. Checks show the flow works, not answer quality.",
                 ""]
        counts: dict[str, int] = {}
        for c in self.checks:
            counts[c.label] = counts.get(c.label, 0) + 1
        lines += ["**Result:** " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())), ""]
        for k, v in self.notes.items():
            lines.append(f"* {k}: {v}")
        lines += ["", "| Step | Check | Result | Detail |", "|---|---|---|---|"]
        for c in self.checks:
            detail = c.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {c.step} | {c.name} | {c.label} | {detail} |")
        return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ API client
class ApiError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"HTTP {status}: {body}")
        self.status, self.body = status, body


class Api:
    def __init__(self, base: str, tenant: str):
        self.base, self.tenant = base.rstrip("/"), tenant

    def call(self, method: str, path: str, body: Any = None, tenant: str | None = None, timeout: float = 120) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Tenant-Id": tenant or self.tenant})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw.decode(errors="replace")
            raise ApiError(exc.code, payload) from None

    def get(self, path: str, **kw: Any) -> Any:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("POST", path, body if body is not None else {}, **kw)

    def put(self, path: str, body: Any, **kw: Any) -> Any:
        return self.call("PUT", path, body, **kw)


def wait_for(what: str, fetch: Callable[[], Any], done: Callable[[Any], bool], timeout: float, every: float = 2.0) -> Any:
    """Fetch until done(value) holds and return that value; raise TimeoutError after timeout seconds."""
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if done(value):
            return value
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out after {timeout:.0f} s waiting for {what}")
        time.sleep(every)


# ------------------------------------------------------------------ fixture website
def serve_site(port: int) -> tuple[socketserver.TCPServer, int]:
    """Serve scripts/demo/safetrip-site on 127.0.0.1; sitemap.xml gets the real port."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # quiet
            pass

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?")[0] == "/sitemap.xml":
                body = (SITE_DIR / "sitemap.xml").read_text(encoding="utf-8").replace("{PORT}", str(self.server.server_address[1])).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(SITE_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ------------------------------------------------------------------ helpers
def tool_calls(call: dict[str, Any]) -> list[dict[str, Any]]:
    return [e.get("data") or {} for e in call.get("events", []) if e.get("kind") == "tool_call"]


def compact(text: str) -> str:
    """The text without spaces, so "$ 1 , 500" and "$1,500" compare equal while RT-17 is open."""
    return re.sub(r"\s+", "", text)


def asks_for_identity(text: str) -> bool:
    return bool(re.search(r"member id|date of birth|policy number|verify your", text, re.I))


def says_not_covered(text: str) -> bool:
    return bool(re.search(r"not covered|isn't covered|aren't covered|excluded|exclusion|not cover|doesn't cover|does not cover|won't cover", text, re.I))


def says_no_info(text: str) -> bool:
    return bool(re.search(r"don't have (specific|approved|any)? ?information|no approved information|don't have details"
                          r"|(does not|doesn't|didn't|do not|don't) (mention|see|find|specify)|not specifically mention", text, re.I))


class Walkthrough:
    def __init__(self, args: argparse.Namespace):
        self.args, self.api, self.r = args, Api(args.api, args.tenant), Report()
        self.site_base = ""
        self.policy_doc: dict[str, Any] | None = None
        self.web_doc_ids: list[str] = []
        self.source_ids: list[str] = []
        self.agent_id = ""

    # 1 -------------------------------------------------------------
    def preflight(self) -> bool:
        print("\n1. Preflight", flush=True)
        try:
            tenants = self.api.get("/api/tenants")["items"]
        except Exception as exc:  # noqa: BLE001
            return self.r.add("1 Preflight", "API reachable", False, f"{self.args.api}: {exc}. Start it with: python scripts/dev.py")
        self.r.add("1 Preflight", "API reachable", True, self.args.api)
        ids = [t["id"] for t in tenants]
        return self.r.add("1 Preflight", f"business unit {self.args.tenant} exists", self.args.tenant in ids, ", ".join(ids))

    # 2 -------------------------------------------------------------
    def website(self) -> None:
        print("\n2. Demo website", flush=True)
        try:
            self.server, port = serve_site(self.args.site_port)
        except OSError:
            self.server, port = serve_site(0)
        self.site_base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(self.site_base + "/help/gadgets.html", timeout=5) as resp:
            self.r.add("2 Website", "fixture site serving", resp.status == 200, self.site_base + "/help/")

    # 3 -------------------------------------------------------------
    def knowledge(self) -> None:
        print("\n3. Knowledge", flush=True)
        docs = self.api.get("/api/knowledge")["items"]
        live = [d for d in docs if d.get("status") != "archived"]
        self.policy_doc = next((d for d in live if d["title"] == POLICY_TITLE), None)
        if self.policy_doc is None:
            text = (DEMO_DIR / "safetrip-policy.md").read_text(encoding="utf-8")
            self.policy_doc = self.api.post("/api/knowledge/text", {"title": POLICY_TITLE, "content": text})
            self.r.add("3 Knowledge", "policy pasted as text", True, f"{len(text)} characters")
        else:
            self.r.add("3 Knowledge", "policy document present", True, "reused from an earlier run")

        try:
            self.api.get("/api/knowledge/sources")
            website_sources = True
        except ApiError:
            website_sources = False
        self.r.notes["Website import"] = "site section (CP-0031)" if website_sources else "single page (From URL, until CP-0031)"
        if website_sources:
            self._website_source()
        else:
            self._single_page(live)

        ids = [self.policy_doc["id"], *self.web_doc_ids]
        hit = self._search("lost baggage limit", ids, source_ids=self.source_ids)
        self.r.add("3 Knowledge", "test search finds the baggage rule", bool(hit) and hit[0]["doc_id"] == self.policy_doc["id"],
                   f"score {hit[0]['score']}" if hit else "no answer")
        para = self._search("my suitcase never arrived, what do I get", ids, source_ids=self.source_ids)
        self.r.add("3 Knowledge", "conversational paraphrase", None, f"score {para[0]['score']}" if para else "no answer (below the score threshold)")
        tail = self._search("travel to a country with a government do-not-travel warning", ids, source_ids=self.source_ids)
        full = bool(tail) and "do-not-travel" in tail[0]["content"]
        self.r.add("3 Knowledge", "search returns the end of the policy (KN-08)", full,
                   "full chunk returned" if full else "the result stops before the do-not-travel exclusion", known="CP-0030")
        phone = self._search("how much do you pay for a stolen phone", ids, source_ids=self.source_ids)
        self.r.add("3 Knowledge", "test search finds the website's gadget page", bool(phone) and "500" in phone[0]["content"],
                   phone[0]["title"] if phone else "no answer")

    def _single_page(self, live: list[dict[str, Any]]) -> None:
        url = self.site_base + "/help/gadgets.html"
        doc = next((d for d in live if d["title"] == "Gadget cover" and d.get("source_type") == "url"), None)
        if doc is None:
            try:
                doc = self.api.post("/api/knowledge/url", {"url": url})
            except ApiError as exc:
                self.r.add("3 Knowledge", "gadget page imported from URL", False, f"{exc}. With CP-0031 set KNOWLEDGE_ALLOW_PRIVATE_URLS=true")
                return
        self.web_doc_ids = [doc["id"]]
        detail = self.api.get(f"/api/knowledge/{doc['id']}")
        content = detail.get("content", "")
        self.r.add("3 Knowledge", "gadget page imported from URL", True, f"{url}, {len(detail.get('chunks', []))} chunk(s)")
        self.r.add("3 Knowledge", "page headings kept as Markdown", "## " in content)
        self.r.add("3 Knowledge", "site header left out of the page (KN-09)", "SafeTrip Help Centre" not in content,
                   "header dropped" if "SafeTrip Help Centre" not in content else "the site's <header> text is indexed with the page", known="CP-0031")

    def _website_source(self) -> None:
        start = self.site_base + "/help/"
        sources = self.api.get("/api/knowledge/sources")["items"]
        src = next((s for s in sources if s.get("start_url") == start and s.get("status") != "archived"), None)
        if src is None:
            src = self.api.post("/api/knowledge/sources", {"start_url": start, "scope": "section", "max_pages": 25, "refresh": "daily",
                                                           "title": "SafeTrip help centre"})
        else:
            try:
                self.api.post(f"/api/knowledge/sources/{src['id']}/sync")
            except ApiError as exc:
                if exc.status != 409:  # 409: a sync is already running; wait for it below
                    raise
        done = wait_for("the website source", lambda: self.api.get(f"/api/knowledge/sources/{src['id']}"),
                        lambda s: s["status"] in ("ready", "partial", "failed"), timeout=180)
        pages = [p for p in done.get("pages", []) if p.get("status") != "archived"]
        self.source_ids = [src["id"]]
        self.r.add("3 Knowledge", "site section indexed (KN-10)", done["status"] == "ready" and len(pages) == 4,
                   f"{done['status']}, {len(pages)} pages")
        self.r.add("3 Knowledge", "robots.txt respected (KN-11)", not any("/private/" in (p.get("url") or "") for p in pages))

    def _search(self, query: str, doc_ids: list[str], source_ids: list[str]) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "doc_ids": doc_ids}
        if source_ids:
            body["source_ids"] = source_ids
        res = self.api.post("/api/knowledge/search", body)
        return res.get("results") or []

    # 4 -------------------------------------------------------------
    def tool_skill_agent(self) -> bool:
        print("\n4. Tool, skill, policy and publish", flush=True)
        tools = self.api.get("/api/tools")["items"]
        tool = next((t for t in tools if t["name"] == TOOL["name"]), None)
        tool = self.api.put(f"/api/tools/{tool['id']}", TOOL) if tool else self.api.post("/api/tools", TOOL)
        self.r.add("4 Build", "tool get_claim_documents", True, TOOL["url"])
        skills = self.api.get("/api/skills")["items"]
        skill = next((s for s in skills if s["name"] == SKILL["name"]), None)
        skill = self.api.put(f"/api/skills/{skill['id']}", SKILL) if skill else self.api.post("/api/skills", SKILL)
        self.r.add("4 Build", "skill 'Help a traveller start a claim'", True)

        agents = self.api.get("/api/agents")["items"]
        found = next((a for a in agents if a["name"] == AGENT_NAME), None)
        agent = found or self.api.post("/api/agents", {"name": AGENT_NAME, "description": AGENT_DESCRIPTION})
        self.agent_id = agent["id"]
        cfg = self.api.get(f"/api/agents/{self.agent_id}")["draft_config"]
        cfg["knowledge_doc_ids"] = [self.policy_doc["id"], *self.web_doc_ids]
        if self.source_ids:
            cfg["knowledge_source_ids"] = self.source_ids
        cfg["tool_ids"], cfg["skill_ids"] = [tool["id"]], [skill["id"]]
        cfg["policy"].update(POLICY)
        self.api.put(f"/api/agents/{self.agent_id}", {"description": AGENT_DESCRIPTION, "draft_config": cfg})
        self.r.add("4 Build", "agent " + ("updated" if found else "created"), True, AGENT_NAME)
        try:
            ver = self.api.post(f"/api/agents/{self.agent_id}/publish", {"change_note": f"Demo walkthrough {datetime.now():%Y-%m-%d %H:%M}"})
        except ApiError as exc:
            return self.r.add("4 Build", "published", False, str(exc))
        self.r.notes["Agent version"] = f"v{ver['version']}"
        agent = self.api.get(f"/api/agents/{self.agent_id}")
        warn_tools = [t for t in [tool] if t.get("requires_verification")]
        self.r.add("4 Build", "published", True, f"v{ver['version']}" + (f", tools needing verification: {len(warn_tools)}" if warn_tools else ""))
        return bool(agent.get("published_version"))

    # 5 -------------------------------------------------------------
    def _chat(self, turns: list[str]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        call = self.api.post("/api/calls", {"agent_id": self.agent_id, "channel": "text"})
        cid, replies = call["call_id"], []
        for text in turns:
            out = self.api.post(f"/api/calls/{cid}/messages", {"text": text}, timeout=180)
            replies.append({"caller": text, **out})
            print(f"      caller: {text}\n      agent:  {out['reply']}", flush=True)
            if out.get("ended") or out.get("escalated"):
                break
        detail = self.api.get(f"/api/calls/{cid}")
        if detail.get("status") != "ended":
            self.api.post(f"/api/calls/{cid}/end")
        return cid, replies, detail

    def test_calls(self) -> None:
        print("\n5. Test calls (text)", flush=True)
        step = "5 Call A"
        cid, rep, detail = self._chat([
            "Hi, my suitcase never showed up after my flight to Rome. How much can I get back for lost baggage?",
            "I also hurt my back skydiving on the trip. Is that covered?",
            "My phone was stolen in Rome too. How much will you pay for a stolen phone?",
            "Can you just promise me my bag claim will be paid?",
            "That's everything, thanks. Bye!",
        ])
        self.call_a = cid
        self.r.notes["Call A"] = cid
        by = {i: t["reply"] for i, t in enumerate(rep)}
        names = [t.get("name") for t in tool_calls(detail)]
        self.r.add(step, "baggage answer from knowledge ($1,500)", bool(re.search(r"1,?500", compact(by.get(0, "")))), by.get(0, "")[:120])
        spoken = [e.get("text") or "" for e in detail.get("events", []) if e.get("kind") == "assistant"]
        self.r.add(step, "API reply equals the stored transcript (RT-17)", by.get(0, "") in spoken,
                   "same text" if by.get(0, "") in spoken else "the API reply has extra spaces inside words and numbers", known="CP-0030")
        self.r.add(step, "agent searched knowledge", "search_knowledge" in names, f"{names.count('search_knowledge')} searches")
        self.r.add(step, "skydiving exclusion", says_not_covered(by.get(1, "")), by.get(1, "")[:120])
        self.r.add(step, "stolen phone answer from the website ($500)", "500" in compact(by.get(2, "")), by.get(2, "")[:120])
        promise = by.get(3, "")
        self.r.add(step, "never-rule held (no promise)", bool(re.search(r"can't|cannot|not able|unable|no guarantee|can not", promise, re.I)), promise[:120])
        self.r.add(step, "call ended by goodbye", any(t.get("ended") for t in rep))

        step = "5 Call B"
        cid, rep, detail = self._chat(["What documents do I need to send for a claim after seeing a doctor in Rome?",
                                       "It was a normal doctor visit, outpatient.", "Thanks, bye."])
        self.r.notes["Call B"] = cid
        first = rep[0]["reply"] if rep else ""
        names = [t.get("name") for t in tool_calls(detail)]
        self.r.add(step, "no request for member ID or date of birth (IDV-09)", not asks_for_identity(" ".join(t["reply"] for t in rep)), first[:120], known="CP-0030", model=True)
        self.r.add(step, "tool get_claim_documents used", "get_claim_documents" in names, ", ".join(n for n in names if n) or "no tools", known="CP-0030", model=True)
        self.r.add(step, "not escalated", not any(t.get("escalated") for t in rep), known="CP-0030", model=True)

        step = "5 Call C"
        cid, rep, detail = self._chat(["Next month I'm going to a country where the government says do not travel. Am I still covered there?",
                                       "OK, thanks. Bye."])
        self.r.notes["Call C"] = cid
        dnt = rep[0]["reply"] if rep else ""
        self.r.add(step, "do-not-travel exclusion answered", says_not_covered(dnt) and not says_no_info(dnt), dnt[:120], known="CP-0030", model=True)

        step = "5 Call D"
        cid, rep, detail = self._chat(["My husband has just been admitted to hospital in Lisbon. What do I do?"])
        self.call_d = cid
        self.r.notes["Call D"] = cid
        self.r.add(step, "escalated to a human (policy trigger)", any(t.get("escalated") for t in rep), rep[-1]["reply"][:120] if rep else "")

    # 6 -------------------------------------------------------------
    def after_calls(self) -> None:
        print("\n6. Scorecard and escalation packet", flush=True)
        try:
            call = wait_for("the scorecard of call A", lambda: self.api.get(f"/api/calls/{self.call_a}"),
                            lambda c: bool(c.get("scorecard")), timeout=240, every=4)
        except TimeoutError as exc:
            self.r.add("6 Score", "call A scored", False, str(exc))
        else:
            sc = call["scorecard"]
            checks = sc.get("checks") or []
            never = [c for c in checks if str(c.get("key", "")).startswith("never.")]
            self.r.add("6 Score", "call A scored", True, f"score {round((sc.get('score') or 0) * 100)} %, hard fail {sc.get('hard_fail')}")
            self.r.add("6 Score", "analysis", None, f"intent {call.get('analysis', {}).get('intent')}, root cause {call.get('analysis', {}).get('root_cause')}")
            if never:
                v = never[0].get("verdict")
                self.r.add("6 Score", "never-rule check passes (SC-14)", v in ("pass", "not_judged"), f"{v}: {never[0].get('reason', '')}", known="CP-0030", model=True)
            failed = [c.get("text", c.get("key")) for c in checks if c.get("verdict") == "fail"]
            self.r.add("6 Score", "failed checks", None, "; ".join(failed)[:300] or "none")
        try:
            call = wait_for("the escalation packet of call D", lambda: self.api.get(f"/api/calls/{self.call_d}"),
                            lambda c: (c.get("escalation") or {}).get("packet_status") == "ready", timeout=120, every=3)
        except TimeoutError as exc:
            self.r.add("6 Escalation", "groundwork packet ready", False, str(exc))
        else:
            esc = call["escalation"]
            summary = str((esc.get("packet") or {}).get("summary") or "")
            self.r.add("6 Escalation", "groundwork packet ready", bool(summary), summary[:160])
            self.r.add("6 Escalation", "waiting in the agent console", esc.get("status") == "waiting", esc.get("reason_category") or "")

    # 7 -------------------------------------------------------------
    def test_suite(self) -> None:
        print("\n7. Test suite", flush=True)
        existing = {s["name"]: s for s in self.api.get(f"/api/agents/{self.agent_id}/scenarios")["items"]}
        for sc in SCENARIOS:
            body = {k: v for k, v in sc.items() if k != "known"}
            if sc["name"] in existing:
                self.api.put(f"/api/scenarios/{existing[sc['name']]['id']}", body)
            else:
                self.api.post(f"/api/agents/{self.agent_id}/scenarios", body)
        start = lambda: self.api.post(f"/api/agents/{self.agent_id}/test-runs", {"target": "published", "repeats": self.args.repeats})  # noqa: E731
        try:
            run_id = start()["eval_run_id"]
        except ApiError as exc:
            if exc.status != 409:
                raise
            print("      a run is in progress; waiting for it", flush=True)
            wait_for("the running suite", lambda: self.api.get(f"/api/agents/{self.agent_id}/test-runs")["items"],
                     lambda runs: all(r["status"] not in ("queued", "running") for r in runs), timeout=900, every=5)
            run_id = start()["eval_run_id"]
        print(f"      {len(SCENARIOS)} scenarios x {self.args.repeats} run(s); this takes a minute or two", flush=True)
        run = wait_for("the test run", lambda: self.api.get(f"/api/test-runs/{run_id}"),
                       lambda r: r["status"] not in ("queued", "running"), timeout=900, every=5)
        self.r.notes["Test run"] = run_id
        for sc in SCENARIOS:
            res = [x for x in run.get("results", []) if (x.get("scenario") or {}).get("name") == sc["name"]]
            ok = bool(res) and all(x.get("passed") for x in res)
            why = "; ".join(f for x in res for f in (x.get("failures") or []))
            self.r.add("7 Tests", f"scenario '{sc['name']}' ({sc['expected']})", ok,
                       f"{sum(1 for x in res if x.get('passed'))}/{len(res)} passed" + (f": {why}" if why else ""), known=sc.get("known"), model=True)

    # 8 -------------------------------------------------------------
    def learning(self) -> None:
        print("\n8. Self-learning (Customer Support & Channels)", flush=True)
        t = self.args.learning_tenant
        clusters = self.api.get("/api/insights/clusters", tenant=t)["items"]
        cl = next((c for c in clusters if "newborn" in c["name"].lower()), None)
        if cl is None:
            self.r.add("8 Learning", "newborn cluster present", False, "not found; reseed with: cd apps/api && uv run voiceai seed --reset")
            return
        detail = self.api.get(f"/api/insights/clusters/{cl['id']}", tenant=t)
        props = [p for p in detail.get("proposals", []) if p.get("status") not in ("rejected", "approved")]
        if not props:
            self.api.post(f"/api/insights/clusters/{cl['id']}/draft-fix", tenant=t)
            detail = wait_for("the drafted fix", lambda: self.api.get(f"/api/insights/clusters/{cl['id']}", tenant=t),
                              lambda d: any(p.get("status") not in ("rejected", "approved", "drafting") for p in d.get("proposals", [])),
                              timeout=240, every=4)
            props = [p for p in detail.get("proposals", []) if p.get("status") not in ("rejected", "approved")]
        prop = props[0]
        self.r.add("8 Learning", "fix drafted", True, f"{prop.get('kind')}: {prop.get('title')}")
        self.api.post(f"/api/proposals/{prop['id']}/evaluate", tenant=t)
        print("      replaying the cluster with simulated callers; about 5-6 minutes", flush=True)
        out = wait_for("the fix evaluation", lambda: self.api.get(f"/api/proposals/{prop['id']}", tenant=t),
                       lambda p: (p.get("eval_run") or {}).get("status") in ("done", "failed"), timeout=1500, every=10)
        s = (out["eval_run"] or {}).get("summary") or {}
        gate = s.get("gate") or {}
        self.r.add("8 Learning", "evaluation finished", out["eval_run"]["status"] == "done",
                   f"cluster {s.get('baseline_pass')}->{s.get('candidate_pass')} of {s.get('cluster_cases')}, held out "
                   f"{s.get('held_out_candidate_pass')}/{s.get('held_out_cases')}, regressions {s.get('regression_pass')}/{s.get('regression_cases')}")
        self.r.add("8 Learning", "no hard fails with the fix", (s.get("hard_fails") or {}).get("candidate", 0) == 0)
        self.r.add("8 Learning", "gate", None, "passed" if gate.get("passed") else "blocked: " + "; ".join(gate.get("reasons") or []))
        self.r.add("8 Learning", "nothing published without a human", None, "the proposal waits in Insights; approve it there if you want")

    # ---------------------------------------------------------------
    def run(self) -> int:
        started = datetime.now()
        print(f"Demo walkthrough against {self.args.api} ({self.args.tenant})")
        if not self.preflight():
            return self.finish(started)
        steps: list[tuple[str, Callable[[], Any]]] = [("website", self.website), ("knowledge", self.knowledge)]
        for name, fn in steps:
            self._guard(name, fn)
        if not self._guard("build", self.tool_skill_agent):
            return self.finish(started)
        for name, fn in [("calls", self.test_calls), ("after calls", self.after_calls), ("test suite", self.test_suite)]:
            self._guard(name, fn)
        if self.args.learning:
            self._guard("learning", self.learning)
        return self.finish(started)

    def _guard(self, name: str, fn: Callable[[], Any]) -> Any:
        try:
            result = fn()
            return True if result is None else result
        except Exception as exc:  # noqa: BLE001 - every step reports instead of stopping the run
            self.r.add(name, f"step '{name}' completed", False, f"{type(exc).__name__}: {exc}")
            return False

    def finish(self, started: datetime) -> int:
        path = Path(self.args.report) if self.args.report else REPORT_DIR / f"demo-{started:%Y%m%d-%H%M%S}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.r.markdown(started, self.args), encoding="utf-8")
        failed = self.r.failed
        known = [c for c in self.r.checks if c.ok is False and c.known]
        fixed = [c for c in self.r.checks if c.ok and c.known and not c.model]
        print(f"\nReport: {path}")
        print(f"{len(failed)} failed, {len(known)} known gaps, {len(fixed)} known gaps fixed, "
              f"{sum(1 for c in self.r.checks if c.ok)} passed in {(datetime.now() - started).seconds} s")
        if self.args.open_agent and self.agent_id:
            print(f"Open the agent: {self.args.api}/agents/edit/?id={self.agent_id}")
        return 1 if failed else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # a Windows console may not encode every reply character
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default="http://localhost:8000", help="API base URL for --live (default http://localhost:8000)")
    ap.add_argument("--tenant", default="evergreen-sandbox", help="business unit for the demo agent")
    ap.add_argument("--learning", action="store_true", help="also draft and evaluate the newborn fix (about 6 minutes, uses LLM calls)")
    ap.add_argument("--learning-tenant", default="evergreen-care", help="business unit for the self-learning step")
    ap.add_argument("--repeats", type=int, default=1, choices=range(1, 6), help="test-suite repeats per scenario (1-5)")
    ap.add_argument("--site-port", type=int, default=8765, help="port for the demo website (default 8765; a free port if taken)")
    ap.add_argument("--report", help="report path (default apps/api/data/demo-runs/demo-<time>.md)")
    ap.add_argument("--no-open-agent", dest="open_agent", action="store_false", help="do not print the builder link")
    ap.add_argument("--serve-site", action="store_true", help="only serve the demo website (for the manual walkthrough) until Ctrl+C")
    ap.add_argument("--live", action="store_true",
                    help="run against --api with its real LLM keys (makes paid model calls); the default is fake mode")
    args = ap.parse_args()
    args.fake = not args.live
    if args.serve_site:
        server, port = serve_site(args.site_port)
        print(f"Demo website: http://127.0.0.1:{port}/help/  (gadget page: http://127.0.0.1:{port}/help/gadgets.html)")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.shutdown()
        return 0
    if args.fake:
        return run_fake(args)
    print(f"LIVE mode: real LLM calls on the keys of {args.api}.", flush=True)
    return Walkthrough(args).run()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_fake(args: argparse.Namespace) -> int:
    """Start scripts/demo/fake_server.py on a free port with a fresh database, run the walkthrough, stop the server."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    port, db_file, log_file = free_port(), REPORT_DIR / f"fake-{stamp}.db", REPORT_DIR / f"fake-{stamp}-server.log"
    print(f"Fake mode: scripted LLM, no API calls. Starting a throwaway API on :{port} (seeding takes a few seconds)…", flush=True)
    with open(log_file, "w", encoding="utf-8") as log:
        server = subprocess.Popen(["uv", "run", "python", str(DEMO_DIR / "fake_server.py"), "--port", str(port), "--db", str(db_file)],
                                  cwd=API_DIR, stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
    try:
        deadline = time.monotonic() + 180
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tenants", timeout=2)
                break
            except OSError:
                if server.poll() is not None or time.monotonic() > deadline:
                    print(f"The fake API did not start; see {log_file}")
                    return 1
                time.sleep(1)
        args.api, args.open_agent = f"http://127.0.0.1:{port}", False  # the server stops after the run: no link to open
        code = Walkthrough(args).run()
    finally:
        stop_tree(server)
    if code == 0:  # keep the database and the server log only when something failed
        for _ in range(10):  # Windows releases the database files a moment after the server process ends
            for f in REPORT_DIR.glob(f"fake-{stamp}*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            if not any(REPORT_DIR.glob(f"fake-{stamp}*")):
                break
            time.sleep(0.5)
    else:
        print(f"Kept for inspection: {db_file} and {log_file}")
    return code


def stop_tree(proc: subprocess.Popen) -> None:
    """Stop `uv run` and the Python server it started: terminating uv alone leaves the server running on Windows."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":
    sys.exit(main())
