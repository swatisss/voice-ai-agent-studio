---
type: Demo Script
title: Demo walkthrough - a new agent from scratch
description: About 25 minutes - build a travel-insurance agent in the empty sandbox business unit from a pasted policy and a web page, publish it, test it by chat, read its scorecard, escalation and test suite, then watch self-learning draft and gate a fix; the same flow runs unattended with scripts/demo_walkthrough.py.
status: draft
tags: [product, demo, onboarding]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# What this shows

The [hackathon demo script](/product/demo-script.md) starts from seeded agents. This walkthrough starts from **nothing**, as a new customer would: an empty business unit, one policy document and one web page. It covers every builder surface (knowledge, tools, skills, policy, persona, publish), the playground, scoring, the human console, test suites and self-learning. Everything is synthetic: *SafeTrip* is a fictional travel insurer.

| Act | Minutes | Where |
|---|---|---|
| 1. Build the agent | 7 | Agents → New agent (sandbox) |
| 2. Talk to it | 6 | Test call |
| 3. What happened | 4 | Calls, Agent console, Evaluation |
| 4. Prove it with tests | 3 | Evaluation → Test suites |
| 5. Learning from escalations | 6 | Insights (Customer Support & Channels) |

**Run it unattended first.** `python scripts/demo_walkthrough.py` performs Acts 1–4 through the API and writes a report (see [Automated run](#automated-run)). Run it before every demo: if it passes, the live demo will too.

# Setup

1. Stack running: `python scripts/dev.py` (web on :3000, API on :8000), with LLM keys in `apps/api/.env` ([/build/runbook-local.md](/build/runbook-local.md)).
2. Demo website: in a second terminal, `python scripts/demo_walkthrough.py --serve-site`. It serves the SafeTrip help centre on `http://127.0.0.1:8765/help/` (pages *Gadget cover*, *Rental car excess cover*, *Medical help abroad*, plus `sitemap.xml` and a `robots.txt` that hides `/help/private/`).
3. Open the app, switch **Business unit** (bottom left) to **New Business Unit (sandbox)**.
4. Have `scripts/demo/safetrip-policy.md` open for copying.
5. If an automated run already created **Travel Cover Helpdesk**, either open it and present Act 1 as a tour, or create **Travel Cover Helpdesk 2**. The tool `get_claim_documents` and the skill *Help a traveller start a claim* are then already in the business unit: tick them instead of creating them (tool names are unique per business unit).

# Act 1 — Build the agent (≈7 min)

| Do | Expect | Say |
|---|---|---|
| **Agents → New agent**. Name `Travel Cover Helpdesk`; description *Answers travellers' questions about what their travel insurance covers, how to make a claim while abroad, and trip cancellation rules.* → **Create** | The builder opens on **Overview**, *Not published* | "Name and one sentence. The description also routes callers to this agent." |
| **Knowledge → Paste text**. Title `SafeTrip travel policy - key benefits`, content from `safetrip-policy.md` → **Add** | A row *SafeTrip travel policy - key benefits*, `text`, ticked | "Ticked means this agent may use it." |
| **From URL** → `http://127.0.0.1:8765/help/gadgets.html` | A row *Gadget cover*, `url`, 3 chunks, split by its headings | "Any page of their website." With [CP-0031](/changes/cp-0031-website-knowledge-sources.md): give `http://127.0.0.1:8765/help/` with *This site section* and the whole help centre is indexed and kept in sync. |
| **Test search**: `lost baggage limit` | The policy, score about 0.72 | "We can check retrieval before any call." |
| **Test search**: `how much do you pay for a stolen phone` | *Gadget cover*, its *What is covered* section | |
| **Policy**: Rules + `Always mention the $100 excess whenever you talk about a medical claim.`; Never + `Never promise that a claim will be approved or paid.`; Escalate when + `The caller or someone travelling with them is in hospital abroad right now.` | Three rows | "Plain-English guardrails. Each one becomes a check on every call." |
| **Tools → New tool**: name `get_claim_documents`, GET, URL `/mock/insurance/claims/requirements`, parameters `{"type":"object","properties":{"claim_type":{"type":"string","enum":["outpatient","urgent_care","inpatient","dental"]}},"required":["claim_type"]}`; both verification boxes off → **Save** | Row ticked | "Tools are set up by the platform team today; customers connect their own systems later ([roadmap](/product/roadmap.md), north star)." |
| **Skills → New skill**: name `Help a traveller start a claim`; use when *The caller wants to make a claim or asks what paperwork they need*; steps *1. Ask what happened and pick the claim type: outpatient (doctor visit), urgent_care, inpatient (hospital stay) or dental. 2. Look up the required documents with get_claim_documents and read them out. 3. Remind them to send everything within 30 days of returning home.*; required tool `get_claim_documents` → **Save** | Row ticked with the tool chip | "A skill is a procedure in plain English that uses tools." |
| **Persona**: show the defaults (Ava, Thalia, greeting, disclosure) | | "The disclosure is required." |
| **Save draft**, then **Publish** with note `First version` | Badge **v1** | |

# Act 2 — Talk to it (≈6 min)

**Test call** opens with the agent selected. Use **Type** (or **Talk** with a headset); keep **Call from** on *No number*; switch **Technical details** on to show the tool chips. Click the message box before each line.

**Call A — answers from knowledge and the web page**

| Caller types | Expect |
|---|---|
| "Hi, my suitcase never showed up after my flight to Rome. How much can I get back for lost baggage?" | `search_knowledge`; up to $1,500, at most $300 per item, $200 for essentials after 12 hours |
| "I also hurt my back skydiving on the trip. Is that covered?" | Excluded: extreme sports |
| "My phone was stolen in Rome too. How much will you pay for a stolen phone?" | From the web page: $500 per item, $1,000 per trip, police report within 24 hours |
| "Can you just promise me my bag claim will be paid?" | Refuses to promise (the Never rule) |
| "That's everything, thanks. Bye!" | Goodbye; *Call ended*; **Was this helpful?** |

**Call B — a skill with a tool**: "What documents do I need to send for a claim after seeing a doctor in Rome?" → the agent asks which kind of claim → "A normal doctor visit, outpatient." → `get_claim_documents` → itemised bill and proof of payment. Since [CP-0030](/changes/cp-0030-knowledge-judge-verification-fixes.md) an agent without a verification tool never asks for a member ID or date of birth.

**Call C — the end of a long passage**: "Next month I'm going to a country where the government says do not travel. Am I still covered there?" → not covered: the exclusion is the last sentence of the policy. Before CP-0030 search returned only the first 700 characters of a chunk and the agent said it had no information.

**Call D — escalation with context**: "My husband has just been admitted to hospital in Lisbon. What do I do?" → hand-off line at once; *Escalated — waiting for a specialist*.

# Act 3 — What happened (≈4 min)

| Do | Expect | Say |
|---|---|---|
| **Agent console** (badge 1) → the waiting escalation | Groundwork packet: summary, reason (safety or the hospital rule), what was tried, sentiment, suggested next step | "The human starts with the whole story." Optionally **Accept**. |
| **Calls** → call A | Transcript with tool chips, outcome *Resolved*, LLM cost about one cent | |
| Scroll to **Scorecard** | Score, a check per rule: Never-rule (hard gate), the $100-excess rule, grounding, tool use, latency | "Every rule we typed is graded on every call." The $100-excess rule often fails on call A: it is a fair catch. The Never-rule check asks "The agent must never do this: … Did the agent stay clear of it?", and a hard-gate fail needs a quote of the breach (CP-0030). |
| **Evaluation** → agent *Travel Cover Helpdesk* | Tiles for v1, the checks with pass rates | "Containment 0 % with one escalated call is expected." |

# Act 4 — Prove it with tests (≈3 min)

**Evaluation → Test suites → New scenario**: name `Lost baggage limit`; caller's goal *Your suitcase never arrived after a flight to Rome. You want to know how much SafeTrip pays for lost baggage.*; persona *Calm*; expected *Resolved*; caller name `Alex Morgan`; other caller details: `policy` = `SafeTrip Standard, bought before the trip` → **Save scenario**. Then **Run suite** with Repeats `1`.

| Expect | Say |
|---|---|
| About a minute later the run finishes; open the simulated call from the run | "A simulated caller plays the scenario against the published version." |

Fill in **other caller details**: with an empty profile the simulated caller acts as a non-member, asks how to join after its answer, accepts a specialist, and the scenario fails as *Expected resolved, got escalated* ([roadmap](/product/roadmap.md) R9).

*Known gap until [roadmap](/product/roadmap.md) R9*: even with the profile the run often fails. The agent answers the baggage question correctly; the simulated caller then invents follow-ups ("Do I need an airline report first?") that the knowledge does not cover, and accepts the specialist the agent offers. Open the simulated call and show it: the agent's answer was right, and the failure belongs to the simulator.

# Act 5 — Learning from escalations (≈6 min)

Switch **Business unit** to **Customer Support & Channels** (seeded history).

| Do | Expect | Say |
|---|---|---|
| **Insights** | Clusters with weekly cost; *Adding a newborn to coverage* and *Prior authorization status* are **Ready for fix**; three are *Correct escalation — no fix* | "The platform separates gaps from escalations that should happen." |
| *Adding a newborn to coverage* → **Draft fix** (about 20 s) | A knowledge article whose every fact comes from what specialists told callers (the **Evidence** table) | "Grounded in what humans actually said." |
| **Run evaluation** (about 5–6 min; start it, then talk through the evidence) | A table: each cluster call, held-out call, derived scenario and test-suite scenario on the current version and with the fix; a gate verdict | "Nothing ships until it is proven, and then only a person approves it." |

Today the gate usually **blocks** this fix: the article answers correctly, but the agent then offers a specialist and the simulated caller accepts ([roadmap](/product/roadmap.md) R7, R9). Present it honestly: the gate did its job, and the reviewer can **Reject**, edit the draft, or **Publish anyway** with a written note.

# Known gaps to mention or avoid

| Gap | Where it shows | Fixed by |
|---|---|---|
| ~~Last part of a long chunk never reaches the agent; never-rule false hard fail; agent asks for an ID it cannot verify; API replies with spaces inside words~~ | Calls B and C, Act 3, automated run | fixed by [CP-0030](/changes/cp-0030-knowledge-judge-verification-fixes.md) |
| One page per URL, no sync, site header indexed with the page | Act 1 From URL | [CP-0031](/changes/cp-0031-website-knowledge-sources.md) |
| Chat box loses focus after each message | Act 2 | [roadmap](/product/roadmap.md) R13 |
| Simulated caller invents follow-ups and accepts hand-offs | Acts 4 and 5 | roadmap R9 |

# Automated run

`scripts/demo_walkthrough.py` (stdlib only) runs Acts 1–4, and Act 5 with `--learning`, against a running stack through the same [REST API](/api/rest-api.md) the web app uses:

```bash
python scripts/dev.py                               # terminal 1: the stack
python scripts/demo_walkthrough.py                  # terminal 2: Acts 1-4, about 2 minutes
python scripts/demo_walkthrough.py --learning       # also Act 5, about 8-10 minutes
python scripts/demo_walkthrough.py --repeats 3      # each test scenario 3 times
python scripts/demo_walkthrough.py --api https://<host> --tenant evergreen-sandbox
python scripts/demo_walkthrough.py --serve-site     # only host the demo website (manual demo)
```

What it does, in order: checks the API and the business unit; serves the demo website on `127.0.0.1:8765` (any free port if taken); pastes the policy and imports the gadget page (or, once `/api/knowledge/sources` exists, indexes the help centre as a website source); runs four test searches; creates or updates the tool, the skill and the agent **Travel Cover Helpdesk** and publishes a new version; holds calls A–D by text; waits for call A's scorecard and call D's groundwork packet; creates or updates four test scenarios and runs the suite; with `--learning`, drafts (or reuses) the newborn fix and evaluates it. It never approves a proposal.

**Report**: printed live and saved to `apps/api/data/demo-runs/demo-<time>.md` (git-ignored), with each check's result and evidence (replies, scores, failures, call ids).

| Result | Meaning |
|---|---|
| PASS | Works |
| FAIL | A regression or an environment problem; the run exits 1 |
| KNOWN (CP-NNNN) | A known gap that change proposal fixes; does not fail the run |
| PASS (fixed) | A deterministic known gap now passes: the CP has landed |
| PASS (not hit) | A known gap that depends on the model did not show this time; it is not proof of a fix |
| INFO | Observation only (scores, analysis, gate verdict) |

The run is repeatable: it reuses the documents, tool, skill, agent and scenarios by name, so each run adds one agent version, four calls and one test run to the sandbox. Use it before a demo, after implementing a CP (its checks should move from KNOWN to PASS (fixed)), and in a scheduled job against a test environment.
