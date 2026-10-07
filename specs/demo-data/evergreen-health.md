---
type: Seed Data
title: Evergreen Health tenants, agents, tools and skills
description: The two demo business units, the persona library, the four agents of Customer Support & Channels with their tools, skills and knowledge, the use-case catalog, and the regression scenarios.
status: stable
tags: [demo-data, seed, healthcare]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Tenants

| id | name | contents |
|---|---|---|
| `evergreen-care` | Evergreen Health · Customer Support & Channels | the four agents, personas, 16 tools, knowledge, use cases, call history |
| `evergreen-sandbox` | Evergreen Health · New Business Unit (sandbox) | empty except one welcome article: shows isolation and building from scratch |

# Persona library (`evergreen-care`)

| Persona | Voice | Speed | Greeting / opening | Style |
|---|---|---|---|---|
| **Ava** | aura-2-thalia-en | 1.0 | "Thanks for calling Evergreen Health member services, this is Ava." | warm, calm, concise; plain language |
| **Grace** | aura-2-helena-en | 0.95 | "Good day, you have reached Evergreen Health member services. My name is Grace." | formal, measured, reassuring |
| **Leo** | aura-2-apollo-en | 1.05 | opening: "Hello, may I speak with {first_name}? This is Leo calling from Evergreen Health about {purpose}." | upbeat, efficient |
| **Maya** | aura-2-andromeda-en | 1.0 | opening: "Hi {first_name}, this is Maya from Evergreen Health. I'm calling to welcome you and help you get set up." | friendly, encouraging |
| **Sage** | aura-2-orion-en | 1.0 | "Evergreen internal knowledge assistant. What do you need to know?" | neutral, precise, short answers |

Every persona carries the disclosure "I'm a virtual assistant, and this call may be recorded for quality." (Sage: "I'm a virtual assistant."). The spoken opening of an inbound call is the greeting followed by the disclosure, so a closing question sits at the end of the disclosure: Ava "... for quality. How can I help you today?", Grace "... How may I assist you?", Sage greeting "Evergreen internal knowledge assistant." with disclosure "I'm a virtual assistant. What do you need to know?". Outbound personas (Leo, Maya) speak their `opening` instead.

# Agents (all published as v1)

| Agent | Mode | Persona | Voice turn detection | Use cases |
|---|---|---|---|---|
| **Customer Care Agent** | inbound | Ava | semantic, heuristic, 700 ms + 1,500 ms | 1, 2, 3, 7 |
| **Renewal Outreach Agent** | outbound (`targets_url` `/mock/insurance/outreach/renewals`) | Leo | semantic | 4 |
| **Welcome & Onboarding Agent** | outbound (`targets_url` `/mock/insurance/outreach/onboarding`) | Maya | semantic | 5 |
| **Internal Knowledge Assistant** | internal | Sage | normal | 6 |

Common policy: verify identity before member data (inbound and outbound); never promise approval; safety screen on; max turns 16. Handoff messages: Customer Care "I'm connecting you with a specialist who will have all the details, so you won't need to repeat yourself."; Renewals "I'll have a renewals specialist call you back shortly."; Onboarding "I'll arrange for a member services colleague to follow up with you."; Internal "I can't answer that reliably, so I'll flag it to the knowledge team."

# Tools (16)

All business-API tools use relative URLs served by the platform ([/api/mock-healthcare-api.md](/api/mock-healthcare-api.md)). `verify` = `requires_verification`.

| Tool | Method and URL | Parameters | Flags | Agents |
|---|---|---|---|---|
| `verify_member` | POST `/mock/healthcare/verify` | `member_id`, `date_of_birth` | is_verification | care, renewals, onboarding |
| `get_member_policies` | GET `/mock/insurance/policies` | — | verify | care |
| `get_policy_details` | GET `/mock/insurance/policies/{policy_id}` | `policy_id` | verify | care |
| `get_member_claims` | GET `/mock/healthcare/claims` | — | verify | care |
| `get_claim_status` | GET `/mock/healthcare/claims/{claim_id}` | `claim_id` | verify | care |
| `get_benefits` | GET `/mock/healthcare/benefits` | — | verify | care |
| `get_coverage_detail` | GET `/mock/insurance/policies/{policy_id}/coverage` | `policy_id`, `benefit` | verify | care |
| `find_providers` | GET `/mock/healthcare/providers` | `specialty`, `zip?` | — | care |
| `list_documents` | GET `/mock/insurance/documents` | `policy_id` | verify | care |
| `request_document` | POST `/mock/insurance/documents/request` | `policy_id`, `document_type`, `delivery`, `countries?`, `travel_start?`, `travel_end?` | verify | care, onboarding |
| `get_renewal_quote` | GET `/mock/insurance/policies/{policy_id}/renewal-quote` | `policy_id` | verify | renewals |
| `record_renewal_decision` | POST `/mock/insurance/policies/{policy_id}/renewal-decision` | `policy_id`, `decision`, `option?`, `callback_time?`, `note?` | verify | renewals |
| `get_onboarding_status` | GET `/mock/insurance/onboarding` | — | verify | onboarding |
| `complete_onboarding_step` | POST `/mock/insurance/onboarding/steps/{step_id}` | `step_id`, `value?` | verify | onboarding |
| `get_authorization_limit` | GET `/mock/internal/authorization-limits` | `role`, `claim_type?` | — | internal |
| `get_escalation_contact` | GET `/mock/internal/contacts` | `topic` | — | internal |

**Tool catalog** (endpoints that exist but are *not* tools in v1; fix drafting may add them): `GET /mock/healthcare/prior-auths/{auth_id}` — "Status of a prior authorization by number (for example PA-77930) for the verified member." Missing → the *prior authorization status* cluster (`missing_skill`).

# Skills

| Agent | Skills (name — use when) |
|---|---|
| Customer Care | **Identity verification** — member-specific request · **Policy inquiry & status** — policies, status, renewal, premium, payments · **Claims status tracking** — claim paid/denied/processing, timeline · **Document center & Green Card** — documents, Green Card for travel abroad · **Coverage information** — benefits, limits, waiting periods, deductible, copays · **Find a provider** — in-network doctors · **Appeals and grievances** — always escalates (`policy_required`) after identifying the claim |
| Renewal Outreach | **Identity verification (outbound call)** — confirm the person and date of birth first · **Renewal conversation** — quote, reasons, options, objections, decision · **Callback scheduling** — "bad time" → record callback |
| Welcome & Onboarding | **Identity verification (outbound call)** · **Welcome checklist** — walk through pending steps, record each · **Digital account and card** — online account, membership card delivery |
| Internal Knowledge Assistant | **Procedure lookup** — search first, cite the article · **Authorization limits** — `get_authorization_limit` · **Escalation contacts** — `get_escalation_contact` |

Skill instruction text lives in the seeder and follows these rows.

# Knowledge bases (OKF, imported per agent)

| Agent | Folder under [/demo-data/kb/](/demo-data/kb/) | Articles |
|---|---|---|
| Customer Care | `customer-care/` | 14: policy types and status, premiums and payments, claim statuses, appeals and grievances, document center, Green Card, coverage benefits overview, waiting periods and exclusions, deductibles and out-of-pocket, copays by plan, finding providers, prior authorization, member ID cards, nurse line and telehealth. **Deliberately missing:** adding a newborn or dependent. |
| Renewal Outreach | `renewals/` | 4 |
| Welcome & Onboarding | `onboarding/` | 4 |
| Internal Knowledge Assistant | `internal/` | 6 |
| *(sandbox tenant)* | `sandbox/` | 1 |

Agents search only their own documents ([/architecture/knowledge.md](/architecture/knowledge.md), KN-05).

# Use-case catalog

Seven rows in `use_cases` for `evergreen-care`, category *Customer Support & Channels*, in the order of [/product/use-cases.md](/product/use-cases.md), each with title, summary, channels (voice, chat), the linked agent, 3–4 sample utterances and the demo callers (name, member ID, date of birth, what to try) from that document.

# Regression scenarios (Customer Care Agent)

| name | caller | goal | expected |
|---|---|---|---|
| Policy status | Maria Lopez | "You want to know if your health policy is active and when it renews." | resolved |
| Claim paid | Maria Lopez | "You want to know whether claim C-20931 was paid and how much you owe." | resolved |
| Green Card for Spain | James Carter | "You are driving to Spain next month and need a Green Card for your car policy, emailed to you." | resolved |
| Dental coverage | Priya Nair | "You want to know how much of your dental allowance is left and whether there is a waiting period." | resolved |
| Policy schedule by email | Daniel Kim | "You want your policy schedule emailed to you." | resolved |
| Appeal denied claim | James Carter | "Your surgery claim C-31544 was denied and you want to appeal it." | escalated |

# Acceptance

- **UC-01** — Given a fresh database, when the seeder runs, then tenant `evergreen-care` has the four agents (modes inbound, outbound, outbound, internal), all published as v1 with the personas, tools, skills and documents listed above, 16 tools in total; tenant `evergreen-sandbox` has one document and no agents.
- **UC-03** — Given the Customer Care Agent and the Internal Knowledge Assistant, when each searches knowledge, then their document sets are disjoint and come from their own folders, and neither can retrieve the other's documents: a question about claims-handler approval limits never returns an internal article for the Customer Care Agent, and a question about the Green Card never returns a customer-care article for the Internal Knowledge Assistant, while each agent's own question finds its own article first (*Authorization limits* for the assistant, *Green Card* for Customer Care).
- **UC-04** — Given the seeded Customer Care Agent, then it has the six regression scenarios above, five expected `resolved` and one `escalated`.
