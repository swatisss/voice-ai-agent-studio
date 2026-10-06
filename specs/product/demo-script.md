---
type: Demo Script
title: Hackathon demo script
description: Three-act, about seven-minute demo proving the loop resolve → escalate well → learn, on seeded Evergreen Health data.
status: stable
tags: [product, demo]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Setup (before presenting)

* App running (local or Cloud Run), tenant **Evergreen Health · Member Services** selected, database freshly seeded (`make seed` / `uv run voiceai seed --reset`).
* Two browser windows: **Test call** (presenter) and **Agent console** (teammate playing the human).
* Headset microphone. Text chat is the fallback for any audio problem — same agent, same flow.
* Dashboard open in a third tab showing ~120 historical calls and the containment trend.

# Act 1 — Resolve (≈2 min)

Caller: **Maria Lopez**, member ID `482913` (EVG-482913), DOB **April 12, 1986**.

| Caller says | Agent does | Visible |
|---|---|---|
| "Hi, I'm calling to check on a claim." | Asks for member ID and date of birth | Live transcript |
| "It's 4-8-2-9-1-3, April 12th, 1986." | `verify_member` → verified | Tool call chip ✓ |
| "Claim C-20931." | `get_claim_status` | Tool result |
| — | "That claim for your dermatology visit on September 10th was paid on September 28th. The plan paid $185 and your share is your $35 specialist copay." | |
| "How much of my deductible is left?" | `get_benefits` | |
| — | "You've met $850 of your $1,500 deductible, so $650 remains." | |
| "That's all, thanks." | `end_call` | Call outcome **Resolved**, cost ≈ $0.01 |

**Message:** routine call contained end-to-end, grounded in real tool results, identity verified before any PHI.

# Act 2 — Escalate with context (≈2 min)

Caller: **James Carter**, member ID `337120`, DOB **November 2, 1979** — speak with frustration.

| Caller says | Agent does |
|---|---|
| "My claim for my emergency surgery got denied and I want to appeal. This is ridiculous, I was in the emergency room!" | Empathizes, asks for ID + DOB |
| "337120, November 2nd 1979." | `verify_member` ✓, `get_member_claims` → finds C-31544 **denied, out-of-network facility** |
| — | Explains the denial reason; appeals require a specialist per policy → `escalate_to_human(policy_required)` → "I'm connecting you with an appeals specialist who will have all the details — you won't need to repeat yourself." |

On the **Agent console** the escalation appears instantly; the packet fills in within a second or two: summary, intent `claim_appeal`, claim `C-31544`, already tried (identity verified, claim looked up: denied, out-of-network facility), reason `policy_required`, sentiment *neutral → frustrated*, suggested next action. The teammate clicks **Accept**, reads the packet aloud, then **Resolve** with disposition `appeal_filed` and a note.

**Message:** the agent knows its limits; the human starts with full context.

# Act 3 — Learn (≈3 min)

1. **Insights** shows clusters from the last four weeks. Top fixable cluster: **"Adding a newborn to coverage"** — 14 escalations, root cause `missing_knowledge`, est. cost/week. Also visible: *Prior authorization status* (`missing_skill`) and *Claim denial appeals* marked **correct escalation — no fix**.
2. Click **Draft fix** → a knowledge article *"Adding a newborn to your coverage"* is drafted from what human agents told those callers (60-day window, member portal → Life events, retroactive to date of birth, birth record needed).
3. Click **Run evaluation** → simulated callers replay the cluster's cases against v1 (baseline) and v1 + article (candidate), plus 6 regression scenarios. Expected: baseline ≈ 0 of 6 cluster cases resolved, candidate ≥ 5 of 6, regressions 6 of 6 pass.
4. Click **Approve** → agent **v2** published; dashboard shows projected containment lift.
5. Live proof: new test call — *"Hi, I just had a baby last week. How do I add him to my plan?"* → resolved from the new article.

**Message:** "we escalated this a lot" became "we fixed it" — with evidence, and a human in control.

# Fallbacks

* Audio fails → use the **Type** tab in Test call for Acts 1–3 (identical behavior).
* LLM provider slow → switch the agent's realtime model in the builder (Groq ↔ OpenRouter).
* Eval takes too long → it streams progress; talk through the per-case results as they arrive.
