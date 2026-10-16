---
type: Seed Data
title: Insurance Claims Agent
description: "The fifth Evergreen Health agent - an inbound claims assistant that runs on the realtime speech-to-speech pipeline: persona, policy, tools, skills, knowledge, mock-API rules and regression scenarios."
status: stable
tags: [demo-data, seed, claims, realtime]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Purpose

A phone-first agent that handles claim questions for Evergreen Health members: where a claim stands, how to report a new one, and what documents are needed. It is the first agent on the **realtime** pipeline ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)) and the agent the phone runbook calls ([/build/runbook-phone.md](/build/runbook-phone.md)). Tenant `evergreen-care`, published as v1, all data synthetic.

# Agent

| Field | Value |
|---|---|
| Name | **Insurance Claims Agent** |
| Description | Answers claim calls: status, new claim (first notice), required documents; hands disputes to a specialist. |
| Mode | inbound |
| Persona | **Nora** (library persona): greeting "Thank you for calling Evergreen Health claims, this is Nora."; disclosure "I'm a virtual assistant, and this call may be recorded for quality. How can I help with your claim?"; style "calm, precise and reassuring; reads numbers slowly; confirms before acting". The persona's Deepgram voice (`aura-2-thalia-en`) is stored but unused in realtime mode. |
| Voice | `pipeline: realtime`; `realtime.voice` unset (the `speech` role default); turn detection `semantic`, `min_silence_ms` 700, interruptions allowed |
| Telephony | `transfer_to: null` (set it in the builder to try a hand-off to a real phone, [/ui/agent-builder.md](/ui/agent-builder.md)) |
| Policy | verify identity (member ID + date of birth) before any claim detail or a new claim; never promise approval or payment dates beyond the claim record; safety screen on; `max_turns` 16; silence 10 s / 30 s, max call 600 s |
| `escalate_when` | the caller disputes a denial or wants to appeal; reports an injury or an emergency; suspects fraud or identity theft; has an estimated loss above $10,000; asks for a person |
| `never` | give medical advice; discuss another person's claim; state that a claim will be approved |
| Handoff message | "I'm connecting you with a claims specialist who will have all the details, so you won't need to repeat yourself." |
| Holding message | "A claims specialist will be with you shortly. Thanks for your patience." |

# Tools (6 — 2 new)

| Tool | Method and URL | Parameters | Flags | New |
|---|---|---|---|---|
| `verify_member` | POST `/mock/healthcare/verify` | `member_id`, `date_of_birth` | is_verification | no (shared) |
| `get_member_claims` | GET `/mock/healthcare/claims` | — | verify | no (shared) |
| `get_claim_status` | GET `/mock/healthcare/claims/{claim_id}` | `claim_id` | verify | no (shared) |
| `get_member_policies` | GET `/mock/insurance/policies` | — | verify | no (shared) |
| `start_claim` | POST `/mock/insurance/claims/first-notice` | `policy_id`, `claim_type`, `service_date`, `provider`, `description`, `estimated_amount?` | verify | **yes** |
| `get_claim_requirements` | GET `/mock/insurance/claims/requirements` | `claim_type` | — | **yes** |

Tools are shared records of the tenant ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)); the tenant now has 18 tools. Mock endpoints: [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md).

# Skills

| Skill | Use when | Instruction outline |
|---|---|---|
| **Identity verification** | any member-specific request | ask for member ID and date of birth, read them back, call `verify_member`; after two failures escalate |
| **Claim status** | "where is my claim" | claim number or `get_member_claims`; `get_claim_status`; say status, what was paid, what is owed, next step in two sentences; denied and disputed → escalate `policy_required` |
| **Report a new claim** | the caller wants to file a claim | verify; `get_member_policies` to pick the policy; collect claim type, service date, provider, short description, rough amount; read the details back and get a yes; `start_claim`; read out the new claim number slowly and the documents still needed; estimated loss above $10,000 → escalate after filing |
| **Required documents** | "what do I need to send" | `get_claim_requirements` for the claim type (no verification needed); say the list in order; offer the upload and email routes from knowledge |
| **Disputes and appeals** | denial disagreement, fraud, injury | always escalates (`policy_required`, `other` for fraud) after identifying the claim |

Skill instruction text lives in the seeder and follows these rows.

# Knowledge base

Folder [/demo-data/kb/claims/](/demo-data/kb/claims/): 3 articles — filing a claim, required documents, claim timelines and payment. Imported for this agent only (KN-05).

# Regression scenarios (4)

| name | caller | goal | expected |
|---|---|---|---|
| Claim paid | Maria Lopez | "You want to know whether claim C-20931 was paid and how much you owe." | resolved |
| New urgent care claim | Aisha Okafor | "You went to Harbor Urgent Care yesterday, paid $150 yourself, and want to file a claim and know what to send." | resolved |
| Documents for a collision | James Carter | "You want to know which documents you need to claim for a minor collision, you do not want to file yet." | resolved |
| Dispute a denial | James Carter | "Your surgery claim C-31544 was denied and you want to dispute it." | escalated |

No historical calls are seeded for this agent: its Calls and Insights fill from real and test calls.

# Use case

The agent serves use case 8, *Claims First Notice & Status* ([/product/use-cases.md](/product/use-cases.md)). Sample utterances: "I want to check on a claim", "I need to report a new claim", "What documents do I need for a dental claim?".

# Acceptance

- **CLM-01** — Given a fresh database, when the seeder runs, then tenant `evergreen-care` has the agent *Insurance Claims Agent* (mode inbound) published as v1 with `voice.pipeline: "realtime"`, persona Nora, the six tools above, the five skills above and the three claims articles as its only knowledge, and every other seeded agent still has `voice.pipeline` `cascade`.
- **CLM-02** — Given the Insurance Claims Agent and the Customer Care Agent, when each searches knowledge, then their document sets are disjoint: "which documents do I need for a collision claim" finds *Required documents* for the claims agent and nothing from the claims folder for the Customer Care Agent.
- **CLM-03** — Given the Insurance Claims Agent, then it has the four regression scenarios above, three expected `resolved` and one `escalated`, and `GET /api/use-cases` returns the eighth use case linked to it with at least two sample utterances.
