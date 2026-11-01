---
type: Change Proposal
title: CP-0025 Supervisor routing and the front desk
description: The front desk opens routed conversations and a supervisor picks the agent in two stages - an embedding shortlist, then a Jev, Laya or LLM decision target with per-decision failover and PHI mode - with clarifying questions, default agents, front-desk phone numbers, a full-flow playground and a live routing trace.
status: stable
cp_state: implemented
tags: [routing, llm, voice, telephony, compliance, ui]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

"Most of the time the tenant people will not know which agent should handle it … if it is for claims it should go to the claim agent." The supervisor routes at the start of a conversation and on transfer, from the catalog of CP-0024. The product owner asked for a decision model like Laya or Jev, both behind one configurable switch with automatic fallback, because Jev's cost and Laya's hosting were unknown. Research (ADR-0012): Jev ≈ $4/month at 10k decisions a day but no BAA; Laya self-hosted ≈ $115/month on a CPU Cloud Run service, CPU latency unmeasured. Third CP of [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).

# What changes

* **Front desk** settings per tenant: persona (greeting, disclosure, voice), pipeline, default agent per scope, confidence threshold override, up to 0–2 clarifying questions, the connecting message, the routing suite's pass mark.
* **Two-stage decision**: Stage A embeds the request against the catalog and routes alone when one agent clearly leads; Stage B asks the decision target to pick among the top 5 (or none) with a confidence.
* **Decision targets** behind one client in Jev's wire format: hosted **Jev** and self-hosted **Laya**; plus the **LLM** router (new gateway role `router`). `ROUTER_DECISION_TARGET` picks the primary (default `jev`); every decision fails over primary → other Jev-format target → LLM → default agent on timeout (350 ms voice / 1.5 s text) or error.
* **`PHI_MODE`** (on by default on Cloud Run) never calls the hosted target.
* **Clarify, then default**: unsure → one LLM-written question → route again → default agent.
* The public API's `agent_id` becomes optional; a routed conversation starts with the front desk, and the chosen agent says its intro and answers.
* **Phone numbers** can target the front desk.
* **Playground**: Test call gets **Single agent | Full flow**; full flow shows the live routing trace.
* **Spike S5** measures Laya on Cloud Run before it becomes the production default.

# Affected specs

* New: [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md) (RTE-01…RTE-11), [/prompts/router-decision.md](/prompts/router-decision.md), [/prompts/router-clarify.md](/prompts/router-clarify.md).
* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) - `router` role, `decision:` targets in `models.yaml` (LG-14).
* [/architecture/tenant-settings.md](/architecture/tenant-settings.md) - front desk settings (MT-16).
* [/architecture/telephony.md](/architecture/telephony.md) - number target `front_desk` (TEL-12).
* [/api/rest-api.md](/api/rest-api.md) - front desk settings, phone-number target, conversation scope (API-13).
* [/api/public-api.md](/api/public-api.md) - `agent_id` optional (PUB-03, PUB-05 as written).
* [/data/data-model.md](/data/data-model.md) - `tenant_settings.front_desk`, `phone_numbers.target` and nullable `agent_id`.
* [/architecture/deployment.md](/architecture/deployment.md) - `ROUTER_*`, `PHI_MODE`, `JEV_API_KEY`, `LAYA_*`, the optional Laya service (DEP-05).
* [/verification/spikes.md](/verification/spikes.md) - S5 (planned).
* [/ui/test-call.md](/ui/test-call.md) (UI-60), [/ui/settings.md](/ui/settings.md) (UI-58).
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) (rule 11), [/product/glossary.md](/product/glossary.md), [/process/conventions.md](/process/conventions.md) (prefix `RTE`).

# Acceptance criteria

New: RTE-01…RTE-11, LG-14, MT-16, TEL-12, API-13, UI-58, UI-60. Each is written in its spec.

# Tasks

1. Spec edits (this CP).
2. Gateway `router` role and the `decision:` section; `voiceai/routing/decision.py` (Jev-format client, targets, thresholds, timeouts, failover chain, `PHI_MODE`) — LG-14, RTE-03, RTE-04.
3. `voiceai/routing/supervisor.py`: candidates by scope, Stage A over catalog entries and knowledge chunks, Stage B, threshold, clarification, default, the routing record and event — RTE-01, RTE-02, RTE-05, RTE-06, RTE-09, RTE-10.
4. Front desk in conversations: greeting, routed first turn, agent intro, front-desk events in the first segment; voice front-desk phase on both pipelines with the connecting message — RTE-07.
5. Front desk settings API and validation — MT-16, API-13.
6. Phone numbers with target `front_desk` — TEL-12, RTE-08.
7. `/healthz` router block — RTE-11.
8. Web: Settings Front desk card; Test call mode switch, scope select and routing trace — UI-58, UI-60.
9. Spike S5 (Laya latency and accuracy), recorded in spikes; the routing-suite tests of CP-0024 (CAT-07, UI-62) run here.
10. Tests citing the IDs; the decision targets are faked in unit tests (no network).

# Risks and rollout

* Jev access is waitlisted and has no BAA: dev and demo use it with synthetic data only; `PHI_MODE` defaults on in the cloud. With no Jev key, the chain falls through to Laya or the LLM automatically.
* Laya's CPU latency is unknown; S5 decides whether voice uses it.
* Confidence scales differ per target; thresholds are per target, and the tenant override applies to whichever answers.
* A routed voice conversation uses the front desk's pipeline and voice, so an agent configured for realtime may run on cascade when reached through the front desk. Reviewed as Open question 1.

# Out of scope

Fine-tuning a classifier on logged decisions; Plano-Orchestrator or GPU hosting; multi-intent splitting of one request; routing outbound calls.

# Open questions for review

1. Routed conversations use the front desk's pipeline and voice for every segment (needed for one voice per conversation). Accept, or require the front desk pipeline to match the agents'?
2. `PHI_MODE` default: on whenever the service runs on Cloud Run. The demo on Cloud Run then needs `PHI_MODE=0` to use Jev. Accept?
