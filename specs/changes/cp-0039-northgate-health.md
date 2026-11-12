---
type: Change Proposal
title: CP-0039 Northgate Health - a UK insurer's help, sales and pre-authorisation in natural language
description: Replaces the Evergreen demo company and its five agents and the SafeTrip kit with Northgate Health, a fictional UK private medical insurer whose click-through help-and-support menus become one front desk and three agents - Customer Care, Health Cover Sales (quote, underwriting, join) and Claims & Pre-authorisation (cashless treatment approval) - keeping the dental kit.
status: stable
cp_state: implemented
tags: [demo-data, seed, mock, use-cases, routing]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Why

The product owner (2026-11-12): the platform "has become too chaotic". Five Evergreen agents (US plans, a motor Green Card, renewal and onboarding outreach, an internal assistant, a realtime claims line) and a travel kit no longer tell one story. The owner wants a real business case: a UK health insurer whose help-and-support site makes people click through topic menus ("Speak to us → choose a topic", one phone number per team) should instead understand what the caller says and route automatically, and the platform should automate the whole health insurance journey by phone - get a quote, choose cover, answer the underwriting questions and register - and then, once insured, get treatment approved cashless through pre-authorisation. Everything except customer care and dental is deleted.

Research (public pages of a UK insurer's help centre, contact menus, claiming guide, cash plan claims form and policy terms, read on 2026-11-12) gave the topics and processes: Direct Access for muscles, bones and joints, mental health and cancer symptoms; the GP open referral; the pre-authorisation code that lets hospitals bill the insurer directly; excess and shortfalls; moratorium, full medical underwriting and switching; quote questions (dates of birth, smoking, postcode, start date); cash plan limits and receipts; missed payments suspend cover. The demo brand is fictional: no real company name appears in code, specs or data.

# What changes

* **One tenant, one story**: `northgate-health` (*Northgate Health · Member & Sales Services*) and an empty `northgate-sandbox` replace `evergreen-care` and `evergreen-sandbox`.
* **Front desk** is seeded: persona Olivia, Customer Care as the default member agent; callers say what they need and the supervisor routes (CP-0025), with transfers between agents mid-call (CP-0026).
* **Three agents** (all inbound, cascade pipeline, British voices): **Customer Care** (Olivia: policy and cover, payments and Direct Debit, details, documents, Digital GP booking, cash plan, renewal/cancellation/complaints/bereavement), **Health Cover Sales** (James: quote, customise, underwriting, join by phone with key facts, declaration and a secure Direct Debit link by email or text), **Claims & Pre-authorisation** (Hannah: cover check, Direct Access or open referral, specialist finder, pre-authorisation codes, claim status, excess and shortfalls).
* **Mock business API** rewritten for UK private medical insurance: payments, secure links, contact details, documents, Digital GP, cash plan, cover check, specialists, pre-authorisations, claims, quotes and a rating table, underwriting with a risk score, applications that create a member and a policy, renewal outreach (MOCK-18…MOCK-31).
* **Knowledge**: 13 + 6 + 8 articles written for Northgate; the newborn article stays deliberately missing.
* **Use cases**: fourteen, category *Member & Sales Services*.
* **Call history and the learning loop** keep their shape (123 calls; *Adding a newborn to the policy* knowledge gap; *Pre-authorisation status* capability gap), rewritten in UK terms.
* **Removed**: Renewal Outreach, Welcome & Onboarding, Internal Knowledge Assistant, the realtime Insurance Claims Agent and their tools, skills, knowledge, scenarios and specs; the SafeTrip kit and its fixture site. Platform features stay (outbound and internal modes, realtime voice, routing, transfer, phone, learning, compliance, sign-in, languages).
* **Kept**: the Oakhaven Dental kit, unchanged; `demo_kits.py dental` now installs it into `northgate-health` so the front desk can route to it.
* Prompts `mode-inbound` and `mode-internal` name Northgate Health; examples in `call-analysis`, `escalation-packet` and `cluster-naming` use Northgate intents and clusters.
* **The safety message uses UK numbers**: 999 for emergencies and Samaritans on 116 123 (in English and Hindi), replacing 911 and 988 ([/product/healthcare-compliance.md](/product/healthcare-compliance.md) rule 6, [/product/compliance-evidence.md](/product/compliance-evidence.md) C5).

# Affected specs

* New: [/demo-data/northgate-health.md](/demo-data/northgate-health.md) (UC-08, UC-09, UC-10, CLM-04, CLM-05; UC-04, UC-06 rewritten for Northgate; UC-01, UC-03, CLM-01…03 retired), [/demo-data/northgate-members.md](/demo-data/northgate-members.md).
* Deleted: `/demo-data/evergreen-health.md`, `/demo-data/claims-agent.md`, `/demo-data/members-and-claims.md`, the Evergreen knowledge folders.
* [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md) - rewritten (MOCK-18…MOCK-31; MOCK-04, 06…14 retired).
* [/product/use-cases.md](/product/use-cases.md) - fourteen use cases (UC-11; UC-02 retired).
* [/demo-data/call-history.md](/demo-data/call-history.md) - UK intents and clusters (UC-05 restated).
* [/demo-data/kb/](/demo-data/kb/) - new articles.
* [/prompts/mode-inbound.md](/prompts/mode-inbound.md), [/prompts/mode-internal.md](/prompts/mode-internal.md) - brand; [/prompts/call-analysis.md](/prompts/call-analysis.md), [/prompts/escalation-packet.md](/prompts/escalation-packet.md), [/prompts/cluster-naming.md](/prompts/cluster-naming.md) - examples.
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md), [/product/compliance-evidence.md](/product/compliance-evidence.md) - UK emergency numbers.
* [/product/demo-script.md](/product/demo-script.md), [/product/demo-walkthrough.md](/product/demo-walkthrough.md), [/product/scope.md](/product/scope.md), [/product/vision.md](/product/vision.md) - the Northgate story.

# Acceptance criteria

New: MOCK-18…MOCK-31, UC-08, UC-09, UC-10, UC-11, CLM-04, CLM-05. Restated with Northgate data, same meaning: MOCK-01, 02, 03, 05, 15, 16, 17, UC-04, UC-05, UC-06. Retired: MOCK-04, MOCK-06…MOCK-14, UC-01, UC-02, UC-03, CLM-01…CLM-03. Every other acceptance ID keeps passing with Northgate data in place of Evergreen data.

# Tasks

1. Specs above, the change log and this CP.
2. `voiceai/mock/data.py`, `voiceai/mock/routes.py` — covers MOCK-*.
3. `voiceai/seed/catalog.py`, `loader.py` (front desk), `history.py` — covers UC-04…UC-11, CLM-04, CLM-05.
4. Platform references: CLI default tenant, memory ID redaction pattern (`NGH-`), the learning tool catalog, prompts.
5. Tests moved to Northgate data; tests of removed agents deleted.
6. Scripts: `demo_walkthrough.py`, `phone_demo.py`, `demo_kits.py` (dental only, default tenant `northgate-health`), fake LLM scripts; SafeTrip files removed; README and web strings.

# Risks and rollout

* Existing local databases hold Evergreen data: run `cd apps/api && uv run voiceai seed --reset` after pulling (the app seeds only an empty database).
* Agents created by hand in the Studio on `evergreen-care` disappear with the reset.
* The live demo uses real voices (`aura-2-pandora-en`, `aura-2-draco-en`); check them by ear once.

# Out of scope

* Real payments or bank details (secure links are mocked); real underwriting rules or prices of any insurer; business and corporate cover; outbound sales calls (outbound mode stays available for agents built in the Studio).
