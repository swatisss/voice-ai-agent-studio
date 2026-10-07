---
type: Demo Script
title: Hackathon demo script
description: About ten minutes - the loop resolve, escalate well, learn on seeded Evergreen Health data, plus a one-minute tour of the other Customer Support & Channels use cases.
status: stable
tags: [product, demo]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Setup (before presenting)

* App running (`python scripts/dev.py` or Cloud Run), business unit **Evergreen Health · Customer Support & Channels** selected, database freshly seeded (`uv run voiceai seed --reset`).
* Two browser windows: **Test call** (presenter) and **Agent console** (a teammate playing the human).
* Headset microphone. **Type** is a full fallback for any audio problem — same agents, same flow.
* Dashboard open in a third tab: 123 historical calls, containment about 68%.
* On Test call, the agent select picks the agent; its "Handles" line names the use cases it serves and the **Test script** card shows the starting phrase of each. Callers' member IDs and dates of birth are not on screen; use [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md) and the callers named below. Switch **Technical details** on to show tool chips and costs.
* In Talk mode the agent opens with its spoken welcome after **Start call**; wait for it, then answer.

# Act 1 — Resolve (≈2 min): Policy Inquiry & Claims Status

Use case **Policy Inquiry & Status**, caller **Maria Lopez**, member ID `482913`, date of birth **April 12, 1986**.

| Caller says | Agent does | Visible |
|---|---|---|
| "Hi, is my health policy still active, and when does it renew?" | asks for member ID and date of birth | live transcript |
| "It's 4-8-2-9-1-3, April 12th, 1986." | `verify_member` → `get_member_policies` → `get_policy_details` | tool chips ✓ |
| — | "Your Silver PPO is active and renews in 25 days. You pay about $212 a month and your next payment is in 9 days." | |
| "What happened with claim C-20931?" (use case **Claims Status Tracking**) | `get_claim_status` | tool result with timeline |
| — | "That dermatology visit was paid on September 28th. The plan paid $185 and your share is your $35 specialist copay." | |
| "That's all, thanks." | `end_call` | outcome **Resolved**, cost about $0.01 |

With semantic turn detection on (Live controls), dictate the member ID slowly with pauses: the agent waits for all six digits instead of cutting in.

# Act 2 — Escalate with context (≈2 min)

Caller **James Carter**, member ID `337120`, date of birth **November 2, 1979**, frustrated.

| Caller says | Agent does |
|---|---|
| "My emergency surgery claim was denied and I want to appeal. This is ridiculous!" | empathizes, asks for ID and date of birth |
| "337120, November 2nd 1979." | `verify_member`, `get_member_claims` → claim C-31544 **denied, out-of-network facility** |
| — | explains the reason; appeals need a specialist → `escalate_to_human(policy_required)` → "I'm connecting you with a specialist who will have all the details — you won't need to repeat yourself." |

On the **Agent console** the escalation appears instantly; the packet fills in within a second or two: summary, intent `claim_appeal`, claim `C-31544`, already tried (identity verified, claim looked up: denied), reason `policy_required`, sentiment *neutral → frustrated*, suggested next action. The teammate clicks **Accept**, reads the packet aloud, then **Resolve** with disposition `appeal_filed` and a note.

# Act 3 — Learn (≈3 min)

1. **Insights** shows clusters from the last four weeks. Top fixable cluster: **"Adding a newborn to coverage"** — 14 escalations, root cause `missing_knowledge`, estimated weekly cost. Also: *Prior authorization status* (`missing_skill`) and *Claim denial appeals* marked **correct escalation — no fix**.
2. **Draft fix** → a knowledge article *"Adding a newborn to your coverage"* is drafted from what human agents told those callers (60-day window, member portal → Life events, retroactive to date of birth, birth record needed).
3. **Run evaluation** → simulated callers replay the cluster's cases against v1 (baseline) and v1 + article (candidate), plus six regression scenarios. Expected: baseline about 0 of 6 cluster cases resolved, candidate at least 5 of 6, regressions 6 of 6.
4. **Approve** → Customer Care Agent **v2** published; the dashboard shows the projected lift.
5. Live proof: new call — *"Hi, I just had a baby last week. How do I add him to my plan?"* → resolved from the new article.

# Use-case tour (≈1 min each, pick what the audience cares about)

| Use case | Select its agent (see the Test script), then | Highlight |
|---|---|---|
| **Document Center & Green Card** | James Carter: "I'm driving to Spain next month, I need a Green Card emailed." | collects countries and dates, issues instantly; try "the USA" → not covered → specialist |
| **Coverage Information Support** | Priya Nair: "How much of my dental allowance is left, is there a waiting period?" | member-specific limit remaining plus the waiting period from knowledge |
| **Outbound Renewal Calls** | choose *James Carter — motor, +8%* and **Place outbound call** | the agent speaks first, verifies date of birth before any price, explains reasons, offers a higher-excess option, records the decision |
| **Policyholder Onboarding** | choose *Aisha Okafor — 5 steps left* and **Place outbound call** | walks the checklist, records each step, sends the membership card |
| **Internal Knowledge Assistant** | "What can a claims handler approve for inpatient?" / "Who do I contact about suspected fraud?" | cites the article, quotes the limit, refuses member-specific data |

# Dynamic controls (≈1 min)

On any voice call open **Live controls**: switch the persona from Ava to Grace mid-call (voice and style change on the next reply), and flip **Normal ↔ Semantic** turn detection to compare how the agent handles a dictated number.

# Fallbacks

* Audio fails → use the **Type** tab for every act (identical behavior).
* LLM provider slow → switch the agent's realtime model in the builder (Groq, OpenRouter or OpenAI).
* Eval takes too long → it streams progress; talk through the per-case results as they arrive.
