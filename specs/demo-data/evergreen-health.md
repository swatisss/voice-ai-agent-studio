---
type: Seed Data
title: Evergreen Health tenants and agents
description: The two demo tenants, their agents, personas, policies, tools, skills, tool catalog and regression scenarios.
status: stable
tags: [demo-data, seed, healthcare]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Tenants

| id | name | industry |
|---|---|---|
| `evergreen-members` | Evergreen Health · Member Services | Health insurance |
| `evergreen-pharmacy` | Evergreen Health · Pharmacy Benefits | Health insurance |

# Agent: Member Services Agent (`evergreen-members`)

Published as **v1** at seed time. Persona: **Ava**, voice `aura-2-thalia-en`.

* Greeting: "Thanks for calling Evergreen Health member services, this is Ava."
* Disclosure: "I'm a virtual assistant, and this call may be recorded for quality. How can I help you today?"
* Style: "Warm, calm and concise. One question at a time. Plain language, no insurance jargon unless the caller uses it."

Policy:

* rules: "Verify identity with member ID and date of birth before sharing any member-specific information." · "When explaining a claim, give its status, what the plan paid, and what the member owes." · "Offer the 24/7 nurse line for health questions."
* escalate_when: "The caller wants to file an appeal or grievance, or disputes a denial." · "The caller reports a provider billing error that needs investigation."
* never: "Promise that a claim, appeal or authorization will be approved." · "Share information about anyone other than the verified member."
* max_turns 16; handoff/holding messages as in [/data/agent-config.md](/data/agent-config.md); safety screen on; voice filler on.

Knowledge: all articles in [/demo-data/kb/member-services/](/demo-data/kb/member-services/). **Deliberately missing:** anything about adding a newborn or dependent — that is the gap the demo discovers.

## Tools

| name | method + url | params | verification |
|---|---|---|---|
| `verify_member` | POST `/mock/healthcare/verify` | `member_id`, `date_of_birth` (YYYY-MM-DD) | **is_verification** |
| `get_benefits` | GET `/mock/healthcare/benefits` | — | requires |
| `get_member_claims` | GET `/mock/healthcare/claims` | — | requires |
| `get_claim_status` | GET `/mock/healthcare/claims/{claim_id}` | `claim_id` | requires |
| `find_providers` | GET `/mock/healthcare/providers` | `specialty`, `zip?` | no |
| `request_id_card` | POST `/mock/healthcare/id-card` | `reason?` | requires |

**Tool catalog** (endpoints that exist but are *not* tools in v1 — available to fix drafting): `GET /mock/healthcare/prior-auths/{auth_id}` — "Status of a prior authorization by number (e.g. PA-77930) for the verified member." Missing → the *prior authorization status* cluster (`missing_skill`).

## Skills

| name | use when | tools | escalate when |
|---|---|---|---|
| Identity verification | Any request needing member-specific data | `verify_member` | Verification fails twice |
| Claim status | Caller asks about a claim | `get_member_claims`, `get_claim_status` | Caller disputes a denial or wants to appeal |
| Benefits and costs | Deductible, out-of-pocket, copays | `get_benefits`, `search_knowledge` | — |
| ID card | Lost, damaged or new ID card | `request_id_card` | — |
| Find a provider | In-network doctors, specialists, facilities | `find_providers` | Caller needs a provider type with no results |
| Appeals and grievances | Caller wants to appeal or complain | `get_claim_status`, `search_knowledge` | Always, after verifying and identifying the claim: escalate with `policy_required` |

(Instructions text for each skill lives in the seeder and follows these rows; `search_knowledge` is a built-in and not listed as a required tool.)

## Regression scenarios

| name | caller | goal | expected |
|---|---|---|---|
| Claim paid | Maria Lopez | "You want to know whether claim C-20931 was paid and how much you owe." | resolved |
| Deductible remaining | Maria Lopez | "You want to know how much of your deductible is left this year." | resolved |
| Replace ID card | James Carter | "You lost your insurance card and want a replacement." | resolved |
| Find dermatologist | Priya Nair | "You want an in-network dermatologist near zip code 94110." | resolved |
| Specialist copay | Daniel Kim | "You want to know your copay for a specialist visit." | resolved |
| Appeal denied claim | James Carter | "Your surgery claim C-31544 was denied and you want to appeal it." | escalated |

# Agent: Pharmacy Benefits Agent (`evergreen-pharmacy`)

Persona **Leo**, voice `aura-2-apollo-en`; greeting "Evergreen Health pharmacy benefits, this is Leo."; same disclosure style. Tools: `verify_member` (same endpoint), `check_formulary` (GET `/mock/pharmacy/formulary`, `drug`), `get_refill_status` (GET `/mock/pharmacy/refills/{rx_id}`, requires verification). Knowledge: [/demo-data/kb/pharmacy/](/demo-data/kb/pharmacy/). Skills: Identity verification, Drug coverage, Refill status. No call history (shows tenant isolation and a fresh onboarding).
