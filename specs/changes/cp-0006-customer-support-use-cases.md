---
type: Change Proposal
title: CP-0006 Customer Support & Channels use cases
description: Rebuild the demo domain around seven health-insurance support use cases - policy inquiry, claims tracking, document center and Green Card, outbound renewals, onboarding, internal knowledge assistant, coverage information - with synthetic tools, knowledge and data, outbound and internal call modes, and a use-case picker.
status: stable
cp_state: implemented
tags: [use-cases, demo-data, outbound]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Why

The demo should show the platform serving a real insurer's customer-support estate, not one generic member-services bot. The target use cases are: Policy Inquiry & Status, Claims Status Tracking, Document Center & Green Card, Outbound Renewal Calls, Policyholder Onboarding, Internal Knowledge Assistant, and Coverage Information Support. Four of them are inbound customer calls, two are calls the agent *places*, and one serves staff - which the platform did not support.

# What changes

1. **Use-case catalog** ([/product/use-cases.md](/product/use-cases.md)): seven use cases, each with an agent, tools, knowledge, skills, sample utterances and demo callers, shown as a gallery on the Test call page and served by `GET /api/use-cases`.
2. **Four agents in one business unit** *Customer Support & Channels*: Customer Care (inbound; use cases 1, 2, 3, 7), Renewal Outreach (outbound; 4), Welcome & Onboarding (outbound; 5), Internal Knowledge Assistant (internal; 6). A second, empty *sandbox* business unit shows tenant isolation and building an agent from scratch.
3. **Call modes** ([/architecture/call-modes.md](/architecture/call-modes.md)): `inbound`, `outbound` (the agent speaks first using the persona's opening; a call context identifies who is being called; identity must still be verified before any account detail), and `internal` (staff audience, internal knowledge only). Outbound targets come from a configurable business-API URL; the UI lets the tester pick whom to call.
4. **Synthetic insurance business API** (`/mock/insurance`, `/mock/internal`): policies, coverage and limits, documents including the international motor insurance certificate (**Green Card**), renewal quotes and decisions, onboarding checklists, outreach target lists, authorization limits and escalation contacts. The pharmacy API, tenant and knowledge are removed (not in the use-case list).
5. **Knowledge**: four OKF knowledge bases (customer care, renewals, onboarding, internal) scoped per agent. The planted gaps for the learning loop remain (adding a newborn, prior-authorization status).
6. The seeded 123-call history and the six regression scenarios are re-expressed in the new tools and intents; totals and clusters are unchanged.

# Affected specs

New: [/product/use-cases.md](/product/use-cases.md), [/architecture/call-modes.md](/architecture/call-modes.md), [/prompts/mode-inbound.md](/prompts/mode-inbound.md), [/prompts/mode-outbound.md](/prompts/mode-outbound.md), [/prompts/mode-internal.md](/prompts/mode-internal.md).
Rewritten: [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md), [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md), [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md), [/product/demo-script.md](/product/demo-script.md), the knowledge bases under [/demo-data/kb/](/demo-data/kb/).
Updated: product vision, scope and glossary; [/demo-data/call-history.md](/demo-data/call-history.md); [/api/rest-api.md](/api/rest-api.md); [/data/agent-config.md](/data/agent-config.md); [/data/data-model.md](/data/data-model.md); [/architecture/agent-runtime.md](/architecture/agent-runtime.md); [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md); [/ui/test-call.md](/ui/test-call.md), [/ui/agent-builder.md](/ui/agent-builder.md), [/ui/calls.md](/ui/calls.md).

# Acceptance criteria

UC-01…UC-05, OB-01…OB-06, MOCK-05…MOCK-12, UI-24…UI-26.

# Tasks

1. Spec edits (done first).
2. Mock insurance and internal APIs; drop pharmacy — MOCK-05…12.
3. Call modes: config fields, `calls.direction`, call context, outbound opening, mode prompts, targets endpoint — OB-01…06.
4. Seed: tenants, personas, 16 tools, skills, four agents, knowledge bases, use cases, scenarios, history — UC-01…05.
5. Web: use-case gallery, outbound call placement, mode badge and select, direction in Calls — UI-24…26.
6. Rename tenant ids (`evergreen-care`, `evergreen-sandbox`) across tests and docs; update tests.

# Risks and rollout

* Large seed (about 30 knowledge articles): the first fastembed seeding takes a little longer; tests use the hash embedder.
* "Green Card" is the international motor insurance certificate; the covered-country list and rules are synthetic and exist only to exercise the flow.
* Outbound calls are simulated in the browser; no telephony, dialer or consent management is built (see scope).
* Out of scope: per-use-case dashboard metrics, regression scenarios for the non-Customer-Care agents, editing use cases in the UI.
