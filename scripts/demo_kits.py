#!/usr/bin/env python3
"""Build ready-to-demo agents from Markdown knowledge: SafeTrip travel insurance and Oakhaven Dental Care.

    python scripts/demo_kits.py dental --check      # no keys, no cost: throwaway API with the scripted fake LLM, build, check, stop
    python scripts/demo_kits.py all --check         # both kits the same way
    python scripts/dev.py                           # in another terminal, then:
    python scripts/demo_kits.py safetrip            # build on the running stack (127.0.0.1:8000) and print the talk track
    python scripts/demo_kits.py dental              # build, then serve the mock patient system the tools call until Ctrl+C
    python scripts/demo_kits.py dental --check --live   # hold the scripted calls on the running stack: REAL (paid) LLM calls

A kit (scripts/demo/kits.py) is one agent: persona, guardrails, knowledge uploaded as Markdown files, tools, skills, use
cases with demo callers. Everything goes through the same REST API as the web app (/api/rest-api.md), lands in the sandbox
business unit and is updated in place on every run (a new published version each time). Publishing also refreshes the
router's capability catalog, which asks the `drafting` model for example phrasings: on the live stack that is the same
small cost as clicking Publish. The dental tools call scripts/demo/dental_mock.py on 127.0.0.1, so the dental agent's
tools work only while this script runs. All businesses, people and records are fictional and synthetic.

Exit code: 0 when every check passed, 1 otherwise. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "demo"))
import dental_mock  # noqa: E402
from demo_walkthrough import (  # noqa: E402
    API_DIR, DEMO_DIR, REPORT_DIR, Api, ApiError, compact, free_port, stop_tree, studio_passwords,
)
from kits import KITS, Chat, Kit  # noqa: E402


def upload(api: Api, path: Path) -> dict[str, Any]:
    """POST /api/knowledge/upload as multipart, exactly like the Knowledge tab's Upload button."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: text/markdown\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(api.base + "/api/knowledge/upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Tenant-Id": api.tenant})
    with api.opener.open(req, timeout=120) as resp:
        return json.loads(resp.read())["items"][0]


def body_of(path: Path) -> str:
    """The Markdown without its frontmatter, as the platform stores it."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        text = text[end + 4:] if end != -1 else text
    return text.strip()


class Runner:
    def __init__(self, args: argparse.Namespace, kit: Kit, mock_base: str = ""):
        self.args, self.kit, self.mock_base = args, kit, mock_base
        self.api = Api(args.api, args.tenant)
        self.results: list[tuple[str, bool | None, str]] = []
        self.agent_id = ""

    def check(self, name: str, ok: bool | None, detail: str = "") -> bool:
        mark = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
        print(f"  [{mark}] {name}" + (f": {detail}" if detail else ""), flush=True)
        self.results.append((name, ok, detail))
        return bool(ok)

    # build ---------------------------------------------------------
    def preflight(self) -> bool:
        try:
            me = self.api.get("/api/auth/me") or {}
        except Exception as exc:  # noqa: BLE001
            return self.check("API reachable", False, f"{self.args.api}: {exc}. Start it with: python scripts/dev.py")
        if me.get("enabled"):
            try:
                self.api.login("admin@echomind.test", studio_passwords(not self.args.live_target)["admin"])
            except ApiError as exc:
                return self.check("signed in as the admin", False, f"{exc}. Set STUDIO_ADMIN_PASSWORD in apps/api/.env")
        ids = [t["id"] for t in self.api.get("/api/tenants")["items"]]
        return self.check(f"business unit {self.args.tenant}", self.args.tenant in ids, ", ".join(ids))

    def knowledge(self) -> list[str]:
        live = [d for d in self.api.get("/api/knowledge")["items"] if d.get("status") != "archived"]
        ids, added, kept = [], 0, 0
        for path in self.kit.knowledge:
            doc = next((d for d in live if d.get("source_type") == "file" and d.get("source_ref") == path.name), None)
            if doc and self.api.get(f"/api/knowledge/{doc['id']}").get("content", "").strip() != body_of(path):
                self.api.call("DELETE", f"/api/knowledge/{doc['id']}")  # the file changed: archive the old copy, upload the new
                doc = None
            if doc is None:
                doc, added = upload(self.api, path), added + 1
            else:
                kept += 1
            ids.append(doc["id"])
        self.check("knowledge uploaded", True, f"{len(ids)} Markdown file(s): {added} uploaded, {kept} unchanged")
        return ids

    def _upsert(self, path: str, items: list[dict[str, Any]], key: str = "name") -> list[dict[str, Any]]:
        existing = {x[key]: x for x in self.api.get(path)["items"]}
        out = []
        for item in items:
            found = existing.get(item[key])
            ours = item.get("url", "").removeprefix(self.mock_base) if "url" in item else ""
            if found and ours and not str(found.get("url", "")).endswith(ours):  # never overwrite someone else's tool
                raise ApiError(409, f"a different tool named {item[key]!r} already exists ({found.get('url')}); rename the kit's tool")
            out.append(self.api.put(f"{path}/{found['id']}", item) if found else self.api.post(path, item))
        return out

    def build(self) -> bool:
        print(f"\n== Build {self.args.agent or self.kit.agent_name} ({self.args.api}, business unit {self.args.tenant})", flush=True)
        if not self.preflight():
            return False
        doc_ids = None if self.args.no_knowledge or self.args.agent else self.knowledge()
        if doc_ids is None:
            self.check("knowledge", None, "left as it is: add files with Knowledge -> Upload, then Save draft and Publish")
        without = set(self.args.without_tool or [])  # left out so the presenter can create them live in the Tools tab
        persona = self._upsert("/api/personas", [self.kit.persona])[0]
        tools = self._upsert("/api/tools", [{**t, "url": t["url"].replace("{mock}", self.mock_base)}
                                            for t in self.kit.tools if t["name"] not in without])
        skills = self._upsert("/api/skills", [s for s in self.kit.skills if not without & set(s["required_tools"])])
        self.check("persona, tools and skills", True, f"{persona['name']}; {len(tools)} tool(s); {len(skills)} skill(s)"
                   + (f"; left out for you: {', '.join(sorted(without))}" if without else ""))

        agents = self.api.get("/api/agents")["items"]
        target = self.args.agent  # an agent the presenter made in the UI: equip it, leave its name, description and knowledge
        found = next((a for a in agents if (target or self.kit.agent_name) in (a["name"], a["id"])), None)
        if target and not found:
            return self.check(f"agent {target!r}", False, f"not in {self.args.tenant}: {', '.join(a['name'] for a in agents)}")
        agent = found or self.api.post("/api/agents", {"name": self.kit.agent_name, "description": self.kit.description})
        self.agent_id = agent["id"]
        cfg = self.api.get(f"/api/agents/{self.agent_id}")["draft_config"]
        keep = lambda ids, new: list(dict.fromkeys([*ids, *new]))  # noqa: E731 - what the presenter added in the UI stays
        cfg.update(persona_id=persona["id"], tool_ids=keep(cfg.get("tool_ids", []), [t["id"] for t in tools]),
                   skill_ids=keep(cfg.get("skill_ids", []), [s["id"] for s in skills]))
        if doc_ids is not None and not target:
            cfg.update(knowledge_doc_ids=doc_ids, knowledge_source_ids=[])
        cfg["policy"].update(self.kit.policy)
        voice_note = ""
        if self.kit.voice_pipeline:
            allowed = (self.api.get("/api/tenant-settings") or {}).get("allowed_pipelines", ["cascade"])
            if self.kit.voice_pipeline in allowed:
                cfg.setdefault("voice", {})["pipeline"] = self.kit.voice_pipeline
                voice_note = f"; voice: {self.kit.voice_pipeline}"
            else:
                voice_note = f"; voice stays {cfg.get('voice', {}).get('pipeline', 'cascade')} ({self.kit.voice_pipeline} is not allowed in Settings)"
        self.api.put(f"/api/agents/{self.agent_id}", {"draft_config": cfg} if target else {"description": self.kit.description, "draft_config": cfg})
        if target:  # the presenter uploads knowledge and publishes on stage
            self.check("draft saved, not published", True, f"{agent['name']}{voice_note}: reload its editor, upload knowledge, then Publish")
        else:
            try:
                ver = self.api.post(f"/api/agents/{self.agent_id}/publish", {"change_note": f"Demo kit {self.kit.key} {datetime.now():%Y-%m-%d %H:%M}"})
            except ApiError as exc:
                return self.check("agent published", False, str(exc))
            self.check("agent published", True, f"{self.kit.agent_name} v{ver['version']} ({'updated' if found else 'created'}){voice_note}")

        existing = {u["title"]: u for u in self.api.get(f"/api/use-cases?agent_id={self.agent_id}")["items"]}
        for n, uc in enumerate(self.kit.use_cases):
            body = {"agent_id": self.agent_id, "category": self.kit.category, "sort": n, **uc}
            if uc["title"] in existing:
                self.api.put(f"/api/use-cases/{existing[uc['title']]['id']}", {k: v for k, v in body.items() if k != "agent_id"})
            else:
                self.api.post("/api/use-cases", body)
        return self.check("use cases", True, f"{len(self.kit.use_cases)} with sample phrasings and demo callers")

    # checks --------------------------------------------------------
    def chat(self, c: Chat) -> None:
        if c.needs_model and not self.args.live_target:
            self.check(c.name, None, "tool conversation: needs a real model (--check --live)")
            return
        call = self.api.post("/api/calls", {"agent_id": self.agent_id, "channel": "text"})
        cid, replies, escalated = call["call_id"], [], False
        for text in c.turns:
            out = self.api.post(f"/api/calls/{cid}/messages", {"text": text}, timeout=180)
            replies.append(out.get("reply") or "")
            escalated = escalated or bool(out.get("escalated"))
            if self.args.verbose:
                print(f"      caller: {text}\n      agent:  {out.get('reply')}", flush=True)
            if out.get("ended") or out.get("escalated"):
                break
        detail = self.api.get(f"/api/calls/{cid}")
        if detail.get("status") != "ended":
            self.api.post(f"/api/calls/{cid}/end")
        searches = [(e.get("data") or {}).get("result") or {} for e in detail.get("events", [])
                    if e.get("kind") == "tool_result" and (e.get("data") or {}).get("name") == "search_knowledge"]
        top = (searches[0].get("results") or [{}])[0] if searches else {}
        found = f"{top.get('title', '')} > {top.get('heading', '')}" if top else "no knowledge hit"
        last = (replies[-1] if replies else "")[:140].replace("\n", " ")
        if self.args.live_target:  # a real model: the reply must say it
            missing = [p for i, pats in c.expect.items() for p in pats if i >= len(replies) or not re.search(p, compact(replies[i]), re.I)]
            ok, why = not missing, (f"missing {missing[0]!r} in: " if missing else "") + last
        else:  # the scripted stand-in only stitches sentences together: the right section must come back first
            ok = not c.source or c.source.lower() in found.lower()
            why = f"top hit {found}" + ("" if ok else f" (expected {c.source!r})")
        ok = ok and (escalated or not c.escalates)
        self.check(c.name, ok, ("escalated; " if escalated else "") + why)

    def mock_checks(self) -> None:
        """The dental tools' backend, called directly (no LLM): verification, slots, booking, fees, cover, estimates, claims."""
        def call(method: str, path: str, body: Any = None, member: str = "") -> tuple[int, Any]:
            req = urllib.request.Request(self.mock_base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json", **({"X-Member-Ref": member} if member else {})})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")

        _, v = call("POST", "/dental/verify", {"patient_id": "10231", "date_of_birth": "12/04/1988"})
        _, bad = call("POST", "/dental/verify", {"patient_id": "OD-10231", "date_of_birth": "1988-04-13"})
        self.check("mock: verify (UK date) and refuse a wrong date of birth", v.get("verified") is True and bad.get("verified") is False)
        _, slots = call("GET", "/dental/slots?practice=Leeds&appointment_type=hygiene")
        _, booked = call("POST", "/dental/appointments", {"slot_id": slots["slots"][0]["slot_id"], "appointment_type": "hygiene"}, "OD-10231")
        self.check("mock: find a slot and book it", str(booked.get("booking_ref", "")).startswith("BK-"), f"{booked.get('booking_ref')} {booked.get('weekday')} {booked.get('time')}")
        _, grace = call("GET", "/dental/appointments", member="OD-10822")
        _, cancel = call("POST", f"/dental/appointments/{grace['appointments'][0]['booking_ref']}/cancel", {}, "OD-10822")
        self.check("mock: late cancellation costs £30", cancel.get("late_cancellation_fee") == 30, cancel.get("fee_note", ""))
        _, reg = call("POST", "/dental/patients", {"first_name": "Sam", "last_name": "Taylor", "date_of_birth": "1999-01-05", "mobile": "07700 900123"})
        status, _ = call("POST", "/dental/appointments", {"slot_id": slots["slots"][1]["slot_id"], "appointment_type": "check_up"}, reg.get("member_ref", ""))
        self.check("mock: new patient registers and must book a new patient exam first", reg.get("verified") is True and status == 422)
        _, crown = call("GET", "/dental/estimate?treatment=crown", member="OD-10231")
        self.check("mock: Priya's crown is in the major waiting period", crown.get("insurance", {}).get("insurance_pays") == 0
                   and crown.get("patient_pays") == 795, crown.get("insurance", {}).get("reason", ""))
        _, molar = call("GET", "/dental/estimate?treatment=root_canal_molar", member="OD-10457")
        self.check("mock: Tom's molar root canal at 80% within his limit", molar.get("insurance", {}).get("insurance_pays") == 556.0,
                   f"insurance pays £{molar.get('insurance', {}).get('insurance_pays')}, Tom pays £{molar.get('patient_pays')}")
        _, claim = call("GET", "/dental/claims/DC-5560", member="OD-10457")
        status, _ = call("GET", "/dental/claims/DC-5560", member="OD-10231")
        self.check("mock: claim status, and another patient's claim is not found", claim.get("status") == "more_information_needed" and status == 404)

    def checks(self) -> None:
        print(f"\n== Check {self.kit.agent_name}" + ("" if self.args.live_target else " (scripted fake LLM: plumbing and retrieval, not answer quality)"), flush=True)
        if self.kit.mock:
            self.mock_checks()
        for c in self.kit.chats:
            try:
                self.chat(c)
            except ApiError as exc:
                self.check(c.name, False, str(exc)[:200])

    # talk track ----------------------------------------------------
    def talk_track(self) -> None:
        print(f"\n== Demo: {self.kit.agent_name}")
        if self.args.web:
            print(f"Open it: {self.args.web.rstrip('/')}/agents/edit/?id={self.agent_id}   (Test call -> Type or Talk)")
        for uc in self.kit.use_cases:
            print(f"\n  {uc['title']}: {uc['summary']}")
            for u in uc["sample_utterances"][:2]:
                print(f"    say: \"{u}\"")
            for c in uc.get("demo_callers", []):
                print(f"    as {c['name']} (ID {c['member_id']}, born {c['date_of_birth']}): {c['try']}")


def run_kits(args: argparse.Namespace, keys: list[str]) -> int:
    mock_server = None
    mock_base = ""
    if any(KITS[k].mock for k in keys):
        try:
            mock_server, port, _ = dental_mock.serve(args.mock_port)
        except OSError:
            mock_server, port, _ = dental_mock.serve(0)
        mock_base = f"http://127.0.0.1:{port}"
        print(f"Mock Oakhaven patient system on {mock_base}/dental/ (the dental tools call it)", flush=True)
    runners, ok = [], True
    try:
        for k in keys:
            r = Runner(args, KITS[k], mock_base)
            runners.append(r)
            if r.build() and args.check:
                r.checks()
        for r in runners:
            if r.agent_id and not args.check:
                r.talk_track()
        failed = [(r.kit.key, n, d) for r in runners for n, s, d in r.results if s is False]
        skipped = sum(1 for r in runners for _, s, _ in r.results if s is None)
        passed = sum(1 for r in runners for _, s, _ in r.results if s is True)
        print(f"\n{passed} passed, {len(failed)} failed, {skipped} skipped")
        ok = not failed and all(r.agent_id for r in runners)
        if mock_server and not args.check and ok:
            print(f"\nServing the mock patient system on {mock_base} for the dental agent's tools. Press Ctrl+C to stop.")
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
    finally:
        if mock_server:
            mock_server.shutdown()
    return 0 if ok else 1


def run_fake(args: argparse.Namespace, keys: list[str]) -> int:
    """scripts/demo/fake_server.py on a free port with a fresh database: no keys, no cost. Kept only when a check failed."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    port, db_file, log_file = free_port(), REPORT_DIR / f"kits-{stamp}.db", REPORT_DIR / f"kits-{stamp}-server.log"
    print(f"Fake mode: scripted LLM, no model calls. Starting a throwaway API on :{port} (seeding takes a few seconds)…", flush=True)
    with open(log_file, "w", encoding="utf-8") as log:
        server = subprocess.Popen(["uv", "run", "python", str(DEMO_DIR / "fake_server.py"), "--port", str(port), "--db", str(db_file)],
                                  cwd=API_DIR, stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
    try:
        deadline = time.monotonic() + 180
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2)
                break
            except OSError:
                if server.poll() is not None or time.monotonic() > deadline:
                    print(f"The fake API did not start; see {log_file}")
                    return 1
                time.sleep(1)
        args.api, args.web = f"http://127.0.0.1:{port}", ""
        code = run_kits(args, keys)
    finally:
        stop_tree(server)
    if code == 0:
        for _ in range(10):  # Windows releases the database files a moment after the server process ends
            for f in REPORT_DIR.glob(f"kits-{stamp}*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            if not any(REPORT_DIR.glob(f"kits-{stamp}*")):
                break
            time.sleep(0.5)
    else:
        print(f"Kept for inspection: {db_file} and {log_file}")
    return code


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # a Windows console may not encode every character; line by line when piped too
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("kit", choices=[*KITS, "all"])
    ap.add_argument("--check", action="store_true", help="hold scripted calls and check the replies (fake LLM unless --live)")
    ap.add_argument("--live", action="store_true", help="with --check: run on --api with its real LLM keys (paid model calls)")
    ap.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL (default http://127.0.0.1:8000; on Windows \"localhost\" tries IPv6 first and costs ~2 s a request)")
    ap.add_argument("--web", default="http://localhost:3000", help="web app base URL for the printed link (default http://localhost:3000)")
    ap.add_argument("--tenant", default="evergreen-sandbox", help="business unit for the agents (default evergreen-sandbox)")
    ap.add_argument("--mock-port", type=int, default=8766, help="port for the mock patient system (default 8766; a free port if taken)")
    ap.add_argument("--agent", metavar="NAME",
                    help="equip an existing agent (made in the UI) with the kit's tools, skills, persona, guardrails and use "
                         "cases; its knowledge, name and description stay, and it is saved as a draft, not published")
    ap.add_argument("--no-knowledge", action="store_true",
                    help="do not upload the kit's knowledge; keep whatever the agent already has (you upload your own files)")
    ap.add_argument("--without-tool", action="append", metavar="NAME",
                    help="leave this tool (and the skills that need it) out, to create it live in the Tools tab; repeatable")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every caller line and reply")
    args = ap.parse_args()
    keys = list(KITS) if args.kit == "all" else [args.kit]
    if args.check and not args.live:
        args.live_target = False
        return run_fake(args, keys)
    args.live_target = True
    if args.check:
        print(f"LIVE checks: real LLM calls on the keys of {args.api}.", flush=True)
    return run_kits(args, keys)


if __name__ == "__main__":
    sys.exit(main())
