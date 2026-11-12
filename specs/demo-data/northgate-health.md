---
type: Seed Data
title: Northgate Health tenants, agents, tools and skills
description: The fictional UK health insurer the demo is built on - two business units, the front desk, the persona library, the three seeded agents with their tools, skills and knowledge, the use-case catalog and the regression scenarios.
status: stable
tags: [demo-data, seed, healthcare, uk]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

Northgate Health is fictional. Its help-and-support topics, products and processes are modelled on public UK private medical insurance help pages (contact menus, claiming and pre-authorisation, cash plans, quotes and underwriting) and turn the click-through menus into one natural-language front desk ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)). Every person, number and record is synthetic ([/demo-data/northgate-members.md](/demo-data/northgate-members.md)). The Oakhaven Dental Assistant is a separate demo kit (`scripts/demo_kits.py dental`) that installs into the same business unit.

# Tenants

| id | name | contents |
|---|---|---|
| `northgate-health` | Northgate Health · Member & Sales Services | the front desk, three agents, three personas, 25 tools, knowledge, 14 use cases, call history; settings allow `cascade` and `realtime`, no own OpenAI key, platform fallback on |
| `northgate-sandbox` | Northgate Health · Sandbox | empty except one welcome article: shows isolation and building from scratch; default settings (cascade only) |

# Front desk

Routed calls (Test call **Full flow**, phone numbers that target the front desk, the public API without `agent_id`) open with persona **Olivia**, then the supervisor picks the agent from the use cases ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)). Default member agent: **Customer Care**. Connecting message: "One moment while I connect you to the right team." Each agent's hand-off intro: Customer Care "You're now with our member services team.", Health Cover Sales "You're now with our health insurance team.", Claims & Pre-authorisation "You're now with our claims and treatment team."

# Persona library (`northgate-health`)

| Persona | Voice | Speed | Greeting | Style |
|---|---|---|---|---|
| **Olivia** | aura-2-pandora-en (British) | 1.0 | "Thanks for calling Northgate Health, this is Olivia." | warm, calm, concise; British English; plain language |
| **James** | aura-2-draco-en (British) | 1.0 | "Thanks for calling Northgate Health, this is James from the health insurance team." | clear, friendly, patient; never pushy; prices said slowly |
| **Hannah** | aura-2-pandora-en (British) | 0.95 | "Thank you for calling Northgate Health claims, this is Hannah." | calm, precise, reassuring; reads codes, dates and amounts slowly |

All three agents also have the built-in contact tools `send_email`, `send_sms` and `place_call` ([CP-0040](/changes/cp-0040-contact-tools.md)).

Every persona's disclosure starts "I'm a virtual assistant, and this call may be recorded for quality and training." and ends with a closing question: Olivia "How can I help you today?", James "Are you looking for a quote today?", Hannah "How can I help with your treatment?".

# Agents (all published as v1, inbound, voice pipeline `cascade`)

| Agent | Persona | Knowledge | Use cases | Max turns |
|---|---|---|---|---|
| **Customer Care** | Olivia | `customer-care/` (13) | 1–7 | 18 |
| **Health Cover Sales** | James | `sales/` (6) | 8–10 | 30 |
| **Claims & Pre-authorisation** | Hannah | `claims/` (8) | 11–14 | 20 |

Turn detection for all three: semantic, heuristic evaluator, 700 ms + 1,500 ms, interruptions allowed.

**Policies** (rules · escalate when · never):

* **Customer Care** — verify before any member detail; never take bank or card details (send a secure link); read new contact details back; transfer treatment approval, consultants and health claim status to claims and new quotes to sales; tell an emergency caller to call 999 · complaints, cancellation, a member has died, adding an adult, removing someone or changing cover mid-term, disputing a charge or cash plan decision · promise payment before pre-authorisation; share another person's information; ask for or repeat bank or card numbers. Hand-off: "I'm connecting you with a colleague who will have all the details, so you won't need to repeat yourself."
* **Health Cover Sales** — non-advised: facts, never a recommendation; one detail at a time with read-back; key facts and declaration read with a clear yes to each before `create_policy`; mention the 21-day cooling-off; no bank details (secure link) · referred to an underwriter, asks for advice, seems confused, vulnerable or under pressure, wants business cover · pressure or "today only" offers; comparing named competitors; medical advice. Hand-off: "I'll pass you to one of our health insurance specialists, who will have your quote in front of them."
* **Claims & Pre-authorisation** — verify first; always `check_treatment_cover` before `create_pre_authorisation`; read codes, numbers, dates and amounts slowly and back; emergencies to 999 or A&E · disputes a decline, exclusion or shortfall; cover needs a clinical decision; distress about a cancer diagnosis; asks for a person · medical advice; another member's claim; saying surgery is approved while pending. Hand-off: "I'm connecting you with a claims specialist who will have all the details, so you won't need to repeat yourself."

# Tools (25)

All business-API tools use relative URLs served by the platform ([/api/mock-healthcare-api.md](/api/mock-healthcare-api.md)). `verify` = `requires_verification`.

| Tool | Method and URL | Parameters | Flags | Agents |
|---|---|---|---|---|
| `verify_member` | POST `/mock/healthcare/verify` | `member_id`, `date_of_birth` | is_verification | care, claims |
| `get_member_policies` | GET `/mock/insurance/policies` | — | verify | care, claims |
| `get_policy_details` | GET `/mock/insurance/policies/{policy_id}` | `policy_id` | verify | care |
| `get_payments` | GET `/mock/insurance/policies/{policy_id}/payments` | `policy_id` | verify | care |
| `retry_missed_payment` | POST `/mock/insurance/policies/{policy_id}/payments/retry` | `policy_id`, `collect_on?` | verify | care |
| `change_collection_day` | POST `/mock/insurance/policies/{policy_id}/payments/collection-day` | `policy_id`, `day` | verify | care |
| `update_contact_details` | POST `/mock/insurance/members/me/contact` | `email?`, `mobile?`, `address?` | verify | care |
| `send_secure_link` | POST `/mock/insurance/secure-links` | `purpose`, `channel`, `policy_id?` | verify | care |
| `list_documents` | GET `/mock/insurance/documents` | `policy_id` | verify | care |
| `request_document` | POST `/mock/insurance/documents/request` | `policy_id`, `document_type`, `delivery` | verify | care |
| `get_gp_slots` | GET `/mock/healthcare/gp/slots` | `type?`, `format?` | verify | care |
| `book_gp_appointment` | POST `/mock/healthcare/gp/appointments` | `slot_id`, `reason`, `patient_name?` | verify | care |
| `get_cash_plan_benefits` | GET `/mock/insurance/policies/{policy_id}/cash-benefits` | `policy_id` | verify | care |
| `get_cash_plan_claims` | GET `/mock/insurance/cash-plan/claims` | — | verify | care |
| `get_cash_plan_claim` | GET `/mock/insurance/cash-plan/claims/{claim_id}` | `claim_id` | verify | care |
| `check_treatment_cover` | GET `/mock/insurance/policies/{policy_id}/eligibility` | `policy_id`, `condition`, `treatment?` | verify | claims |
| `find_specialists` | GET `/mock/healthcare/specialists` | `specialty?`, `condition?`, `postcode?`, `policy_id?` | — | claims |
| `create_pre_authorisation` | POST `/mock/healthcare/pre-authorisations` | `policy_id`, `condition`, `treatment`, `symptoms_started`, `referral?`, `specialist_id?`, `gp_first_seen?`, `patient_name?` | verify | claims |
| `get_pre_authorisation` | GET `/mock/healthcare/prior-auths/{auth_id}` | `auth_id` | verify | claims |
| `get_member_claims` | GET `/mock/healthcare/claims` | — | verify | claims |
| `get_claim_status` | GET `/mock/healthcare/claims/{claim_id}` | `claim_id` | verify | claims |
| `create_quote` | POST `/mock/sales/quotes` | `people[]`, `postcode`, `start_date?`, `occupation?` | — | sales |
| `price_quote` | POST `/mock/sales/quotes/{quote_id}/price` | `quote_id`, `package?`, `product?`, `outpatient_limit?`, `excess?`, `hospital_list?`, `add_ons?` | — | sales |
| `assess_underwriting` | POST `/mock/sales/quotes/{quote_id}/underwriting` | `quote_id`, `method`, `answers?`, `previous_insurer?`, `continuous_cover_months?` | — | sales |
| `create_policy` | POST `/mock/sales/applications` | `quote_id`, `underwriting_id`, `policyholder`, `documents_by?`, `payment_link_by?`, `key_facts_confirmed`, `declaration_confirmed`, `marketing_opt_in?` | — | sales |

**Tool catalog** (endpoints that exist but are *not* Customer Care tools in v1; fix drafting may add them): `GET /mock/healthcare/prior-auths/{auth_id}` — "Status of a pre-authorisation by code (e.g. PA-500955) for the verified member." Members who ask member services for a pre-authorisation status form the *Pre-authorisation status* cluster (`missing_skill`), the capability gap of the learning demo.

# Skills

| Agent | Skills (name — use when) |
|---|---|
| Customer Care | **Identity verification** · **Policy and cover questions** — who is covered, excess, outpatient limit, hospital list · **Payments and Direct Debit** — collection, missed payments, collection day, bank details by secure link · **Update contact details** · **Documents and membership card** · **Book a Digital GP appointment** — 999 first for emergencies · **Cash plan** — limits, claims, how to claim · **Send details by email or text** — registered contact first, read-back, short message, no membership number (contact tools, [/architecture/contact-tools.md](/architecture/contact-tools.md)) · **Renewal, cancellation, complaints and bereavement** — explain, then hand over |
| Health Cover Sales | **Health insurance quote** — who, dates of birth, smoking, postcode, start date; offer to email the quote summary · **Choose and customise cover** — one option at a time, re-price, facts not advice · **Underwriting questions** — moratorium, full medical, switch · **Join and register** — details, key facts, declaration, two clear yeses, `create_policy` |
| Claims & Pre-authorisation | **Identity verification** · **Get treatment approved (pre-authorisation)** — condition, onset, GP, cover check, specialists, code, then offer to text the code · **Find a consultant or hospital** · **Pre-authorisation and claim status** · **Excess, shortfalls and invoices** |

Skill instruction text lives in the seeder and follows these rows.

# Knowledge bases (OKF, imported per agent)

| Agent | Folder under [/demo-data/kb/](/demo-data/kb/) | Articles |
|---|---|---|
| Customer Care | `customer-care/` | 13: contact lines and hours, your policy explained, premiums and Direct Debit, missed payments, changing your details, documents and membership card, Digital GP and nurse line, cash plan explained, cash plan claims, renewal and cancellation, complaints, bereavement, accessibility. **Deliberately missing:** adding a newborn to a policy (the knowledge gap the learning loop finds). |
| Health Cover Sales | `sales/` | 6: products, cover options and add-ons, how prices are worked out, underwriting, joining and cooling-off, who can join |
| Claims & Pre-authorisation | `claims/` | 8: how to get treatment, Direct Access, open referrals, pre-authorisation codes, finding a specialist, excess and shortfalls, claims and invoices, what is not covered |
| *(sandbox tenant)* | `sandbox/` | 1 |

Agents search only their own documents ([/architecture/knowledge.md](/architecture/knowledge.md), KN-05).

# Use-case catalog

Fourteen rows in `use_cases` for `northgate-health`, category *Member & Sales Services*, in the order of [/product/use-cases.md](/product/use-cases.md), each with title, summary, channels (voice, chat), the linked agent, 3–4 sample utterances and the demo callers (name, membership number, date of birth, what to try; prospects have no membership number).

# Regression scenarios

**Customer Care** (8):

| name | caller | persona | expected | expectations |
|---|---|---|---|---|
| Policy cover by text | Sarah Mitchell | calm | resolved | requires `verify_member` and `send_sms` with `to: registered` |
| Missed payment | David Okoro | calm | resolved | requires `get_payments` and `retry_missed_payment` with `policy_id: PMI-300214` |
| Digital GP for my daughter | Sarah Mitchell | impatient | resolved | requires `book_gp_appointment` |
| Cash plan optical limit | Lucy Evans | confused | resolved | requires `get_cash_plan_benefits` with `policy_id: CSH-400118` |
| Membership certificate by email | Raj Patel | calm | resolved | requires `request_document` with `document_type: membership_certificate`, `delivery: email`; result `status` = `queued` |
| Complaint | Raj Patel | calm | escalated | — |
| Wrong date of birth first | Emma Clarke | adversarial | resolved | requires `verify_member` and `update_contact_details` |
| Remembers email preference | Sarah Mitchell | calm | resolved | memory "Prefers documents by email"; requires `request_document` with `document_type: membership_card`, `delivery: email` |

**Claims & Pre-authorisation** (4): *Knee pain, Direct Access* (Sarah; requires `check_treatment_cover` and `create_pre_authorisation` on `PMI-300101` and `send_sms` to the registered mobile; resolved) · *Pre-authorisation status* (Emma; `get_pre_authorisation` `PA-500955`; resolved) · *Shortfall explained* (David; `get_claim_status` `CL-70412`; resolved) · *Excluded back treatment* (Raj disputes `CL-70640`; escalated).

**Health Cover Sales** (3): *Couple quote and join* (Alex Morgan with partner Sam, BS6 6JY, Balanced, moratorium; requires `create_quote`, `price_quote`, `assess_underwriting`, `create_policy`; resolved) · *Smoker asks the price* (Gareth Lewis, London, impatient; `create_quote`, `price_quote`, `send_email` of the quote to the address he gives; resolved) · *Asks for advice* (Nina Shah, confused; escalated).

# Acceptance

- **UC-06** — Given a fresh database, when the seeder runs, then `northgate-health` has `allowed_pipelines` `["cascade","realtime"]` with platform fallback on and no stored key, and `northgate-sandbox` has no settings row (cascade only).
- **~~UC-01~~** — Retired by CP-0039: the five Evergreen agents are replaced by the three Northgate agents (UC-08). Was: tenant `evergreen-care` had five agents and 18 tools.
- **~~UC-03~~** — Retired by CP-0039: the Internal Knowledge Assistant no longer exists; knowledge isolation between the Northgate agents is UC-09.
- **UC-04** — Given the seeded Customer Care agent, then it has the eight test scenarios above with their personas and expectations, seven expected `resolved` and one `escalated`, all enabled.
- **UC-08** — Given a fresh database, when the seeder runs, then tenant `northgate-health` has the three agents Customer Care, Health Cover Sales and Claims & Pre-authorisation, all inbound, on the `cascade` pipeline and published as v1 with the personas, tools, skills and documents listed above, 25 tools in total; tenant `northgate-sandbox` has one document and no agents.
- **UC-09** — Given the three agents, when each searches knowledge, then their document sets are disjoint and come from their own folders: "what is moratorium underwriting" finds the underwriting article for Health Cover Sales and nothing from the sales folder for Customer Care; "what is a shortfall" finds *Excess and shortfalls* for Claims & Pre-authorisation only.
- **UC-10** — Given a fresh database, then the front desk of `northgate-health` uses persona Olivia with Customer Care as the default member agent and the connecting message above; Health Cover Sales has the three sales scenarios (two `resolved`, one `escalated`) and Claims & Pre-authorisation the four claims scenarios (three `resolved`, one `escalated`); no Health Cover Sales tool requires verification.
- **~~CLM-01~~** — Retired by CP-0039: the realtime Insurance Claims Agent (Nora) is replaced by Claims & Pre-authorisation (CLM-04).
- **~~CLM-02~~** — Retired by CP-0039: replaced by UC-09.
- **~~CLM-03~~** — Retired by CP-0039: replaced by CLM-05.
- **CLM-04** — Given a fresh database, when the seeder runs, then *Claims & Pre-authorisation* has persona Hannah, the eight tools listed above, the five skills above and the eight claims articles as its only knowledge; Customer Care has no claims or pre-authorisation tool (the capability gap stays in the catalog).
- **CLM-05** — Given the seeded catalog, then `GET /api/use-cases` returns use cases 11–14 linked to Claims & Pre-authorisation and 8–10 linked to Health Cover Sales, each with at least three sample utterances.
