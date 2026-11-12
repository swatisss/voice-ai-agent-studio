---
type: Demo Script
title: Hackathon demo script
description: About twelve minutes on seeded Northgate Health data - a Customer Care call, front-desk routing and a transfer, a quote to join by phone, a pre-authorisation, an escalation with its groundwork packet, and the learning loop on "Adding a newborn to the policy".
status: stable
tags: [product, demo]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# The story

Northgate Health is a fictional UK private medical insurer ([/demo-data/northgate-health.md](/demo-data/northgate-health.md)). A traditional help-and-support site makes members click through "Speak to us → choose a topic" and ring a different number per team. Here one front desk listens to what the caller says and routes them to **Customer Care**, **Health Cover Sales** or **Claims & Pre-authorisation**; the agents resolve, hand over well, and learn from what people tell callers.

# Setup (before presenting)

* App running (`python scripts/dev.py` or Cloud Run), business unit **Northgate Health · Member & Sales Services** selected, database freshly seeded (`cd apps/api && uv run voiceai seed --reset`).
* Two browser windows: **Test call** (presenter) and **Agent console** (a teammate playing the specialist).
* Headset microphone. **Type** is a full fallback for any audio problem: same agents, same flow.
* Dashboard open in a third tab: 123 historical calls, containment about 68%.
* On Test call, the agent select picks the agent; its "Handles" line names its use cases and the **Test script** card shows a starting phrase for each. Callers' membership numbers and dates of birth are not on screen; use [/demo-data/northgate-members.md](/demo-data/northgate-members.md) and the callers named below. Switch **Technical details** on to show tool chips and costs.
* In Talk mode the agent opens with its spoken welcome after **Start call**; wait for it, then answer.

# Act 1 — Resolve (≈2 min): Customer Care

**Customer Care** (persona Olivia), caller **Sarah Mitchell**, membership number `NGH-410237`, born **14 March 1984**. Use cases *Policy & Cover Questions* and *Book a Digital GP Appointment*.

| Caller says | Agent does | Visible |
|---|---|---|
| "Hi, who's covered on my policy, and what's my excess?" | asks for membership number and date of birth | live transcript |
| "It's 4-1-0-2-3-7, the 14th of March 1984." | `verify_member` → `get_member_policies` → `get_policy_details` | tool chips ✓ |
| — | "Your Northgate Complete policy covers you, Ben and Isla. Your excess is £100 per person each policy year, and you have unlimited outpatient cover on the Extended hospital list." | |
| "Isla's had a temperature for two days. Can she see a GP by video tomorrow?" | `get_gp_slots` → reads the times → `book_gp_appointment` for Isla | booking reference `GPB-…` |
| "That's all, thanks." | `end_call` | outcome **Resolved**, cost about one penny |

With semantic turn detection on (Live controls), dictate the membership number slowly with pauses: the agent waits for all six digits instead of cutting in.

# Act 2 — One front desk (≈2 min): routing and a transfer

Switch Test call to **Full flow**, audience *Members*, **Type**. Caller **Emma Clarke**, `NGH-638405`, born **21 June 1991**.

| Caller says | What happens |
|---|---|
| — | Olivia's front-desk greeting and disclosure |
| "I'm waiting to hear if my shoulder operation has been approved." | "One moment while I connect you to the right team." → notice **Routed to Claims & Pre-authorisation**; the Routing card shows the candidates and scores |
| "638405, 21st of June 1991." | Hannah verifies → `get_pre_authorisation` `PA-500955`: **pending**, waiting for the consultant's procedure code and fee estimate, decision in about two days |
| "While I have you, can I move my Direct Debit to the 15th?" | `transfer_to_agent` → notice **Transferred to Customer Care** → "You're now with our member services team." → `change_collection_day` without asking her to verify again |

"No menu, no second phone number, and she never repeats herself."

# Act 3 — Quote to join (≈3 min): Health Cover Sales

**Health Cover Sales** (persona James) asks nobody to verify: callers are not members yet. Caller **Alex Morgan**, born 5 May 1990, with partner **Sam**, born 2 February 1992, non-smokers, postcode **BS6 6JY** (use cases 8–10).

| Caller says | Agent does |
|---|---|
| "Hi, I'd like a quote for private health insurance for me and my partner." | asks one thing at a time: names, dates of birth, smoking, postcode, start date |
| (answers) | `create_quote` → three packages read slowly: Essentials about £50.65, Balanced about £80.94, Complete about £97.85 a month |
| "What's the difference between Balanced and Complete?" | facts, not advice: outpatient limit, excess, hospital list; `price_quote` after each change |
| "Balanced, please. I had asthma as a child, is that a problem?" | explains moratorium and full medical underwriting → full medical → `assess_underwriting`: accepted with "asthma and related conditions" excluded for Alex, about 5% cheaper |
| "OK, let's do it." | reads back the details, the key facts and the declaration, waits for a clear yes to each → `create_policy` → policy and membership numbers, start date, documents and a secure Direct Debit link by email, the 21-day cooling-off |

# Act 4 — Get treatment approved (≈2 min): Claims & Pre-authorisation

Single agent **Claims & Pre-authorisation** (persona Hannah), caller **Sarah Mitchell**.

| Caller says | Agent does |
|---|---|
| "I've had knee pain for about three weeks. Can I get it seen without going to my GP?" | verifies → `check_treatment_cover`: covered, **Direct Access** (no GP referral), a pre-treatment form because the policy is on moratorium |
| "Someone near Leeds, please." | `find_specialists`: Mr James Holloway, Headingley Park Hospital, fee-assured, first appointment in about six days |
| "Yes, book that in." | reads back → `create_pre_authorisation` → code **PA-502001**, valid 90 days, nothing to pay (her excess is already used this year) |

"The hospital bills us directly with that code: no paying up front and claiming back."

# Act 5 — Escalate with context (≈2 min)

Same agent, caller **Raj Patel**, `NGH-714560`, born **30 November 1966**, frustrated.

| Caller says | Agent does |
|---|---|
| "My back injection claim was declined and I want it looked at again. This is ridiculous!" | acknowledges, asks for membership number and date of birth |
| "714560, 30th of November 1966." | `verify_member`, `get_member_claims` → `get_claim_status` `CL-70640`: **declined**, lower back conditions are excluded on his policy |
| — | explains the exclusion; disputes go to a person → `escalate_to_human(policy_required)` → "I'm connecting you with a claims specialist who will have all the details, so you won't need to repeat yourself." |

On the **Agent console** the escalation appears at once; the groundwork packet fills in within a second or two: summary, intent `claim_dispute`, claim `CL-70640`, already tried (identity verified, claim looked up: declined, exclusion), reason `policy_required`, sentiment *neutral → frustrated*, suggested next action. The teammate clicks **Accept**, reads the packet aloud, then **Resolve** with a note.

# Act 6 — Learn (≈3 min): "Adding a newborn to the policy"

1. **Insights** shows clusters from the last four weeks. Top fixable cluster: **Adding a newborn to the policy**, 14 escalations, root cause `missing_knowledge`, estimated weekly cost. Also: *Pre-authorisation status* (`missing_skill`: Customer Care has no lookup tool) and *Complaints* marked **correct escalation — no fix**.
2. **Draft fix** → a knowledge article *Adding a newborn to your policy* drafted from what specialists told those callers (add the baby within 3 months of birth with no medical questions; cover starts from the day we are told; the baby shares the family excess; normal childbirth is not covered; a new membership certificate within 5 working days).
3. **Run evaluation** → simulated callers replay the cluster's cases against v1 (baseline) and v1 + article (candidate), plus Customer Care's eight regression scenarios. Expected: baseline about 0 of 6 cluster cases resolved, candidate at least 5 of 6, no regression.
4. **Approve** → Customer Care **v2** published; the dashboard shows the projected lift.
5. Live proof: new call — *"Hi, I had a baby last week. How do I add her to my policy?"* → resolved from the new article.

# Tour (≈1 min each, pick what the audience cares about)

| Use case | Agent and caller | Highlight |
|---|---|---|
| **Payments & Direct Debit** | Customer Care, David Okoro: "My Direct Debit bounced, am I still covered?" | cover suspended until the £61.20 is paid; retry in 3 days with a reference; bank details only by secure link |
| **Cash Plan Cover & Claims** | Customer Care, Lucy Evans: "What's happening with my glasses claim?" | £220 claimed against a £200 optical limit, still processing |
| **Documents & Membership Card** | Customer Care, Raj Patel: "Can you email me my membership certificate?" | queued to a masked email address |
| **Find a Consultant or Hospital** | Claims & Pre-authorisation, Emma Clarke: "I need an orthopaedic surgeon near Bristol." | fee-assured specialists on her hospital list first |
| **Excess, Shortfalls & Invoices** | Claims & Pre-authorisation, David Okoro: "Why did I get a bill for £60?" | a shortfall: the consultant is not fee-assured |
| **Dental** | `python scripts/demo_kits.py dental`, then Full flow: "I need a dental check-up." | the front desk routes to the Oakhaven Dental Assistant |

# Dynamic controls (≈1 min)

On any voice call open **Live controls**: switch the persona from Olivia to Hannah mid-call (voice and style change on the next reply), and flip **Normal ↔ Semantic** turn detection to compare how the agent handles a dictated number.

# Fallbacks

* Audio fails → use the **Type** tab for every act (identical behaviour).
* LLM provider slow → switch the agent's realtime model in the builder (Groq, OpenRouter or OpenAI).
* Eval takes too long → it streams progress; talk through the per-case results as they arrive.
