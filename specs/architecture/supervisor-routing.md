---
type: Component Spec
title: Supervisor routing
description: The front desk and the supervisor that picks which agent handles a conversation - the embedding by default or a configured decision model with embedding fallback, PHI mode, clarification, default agent, phone numbers and the playground, and the routing record and trace.
status: stable
tags: [architecture, routing, llm, voice, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Purpose

Callers and tenant systems do not know the tenant's agents. The **front desk** opens the conversation and the **supervisor** decides which agent handles it, from the [capability catalog](/architecture/capability-catalog.md). The supervisor runs at the start of a conversation and when an agent asks for a [transfer](/architecture/agent-transfer.md); it is never part of an agent's turns. Decision: [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).

# Conversations

A **conversation** (`conversations`, [/data/data-model.md](/data/data-model.md)) is one caller connection: a public-API conversation, a playground full-flow test or a phone call to a front-desk number. It has a `scope` (`member` or `staff`), a `source` (`api`, `playground`, `phone`), the routing decisions, and one **segment** (a `calls` row) per agent that handled it.

* **Explicit agent.** A conversation created with `agent_id` starts its first segment on that agent (`routed_by: explicit`); the voice and pipeline are the agent's.
* **Routed.** Otherwise the front desk speaks first: its persona's greeting and disclosure ([/product/healthcare-compliance.md](/product/healthcare-compliance.md) rule 2). The caller's first utterance (or the API `message`) is routed; the chosen agent says its `handoff_intro` and answers that utterance without greeting again. Front-desk lines and the routed utterance are stored as the first events of the first segment (`data.front_desk: true`), so its transcript is complete. A conversation that ends before routing has no segment.
* **Voice and pipeline.** A routed conversation uses the front desk's persona voice and pipeline for every segment; a conversation with an explicit agent uses that agent's. An agent's own voice and pipeline apply when it is called directly.

# Front desk settings

Part of tenant settings (`tenant_settings.front_desk`, [/architecture/tenant-settings.md](/architecture/tenant-settings.md)):

| Setting | Rules | Default |
|---|---|---|
| `persona_id` | a library persona of the tenant ([/architecture/personas.md](/architecture/personas.md)): greeting, disclosure, voice | the first persona by name |
| `pipeline` | `cascade` or `realtime` (must be allowed) | `cascade` |
| `default_agents` | `{member, staff}`: a routable agent of that scope or `null` | `null` |
| `min_confidence` | 0–1 or `null` (the decision model's own threshold) | `null` |
| `max_clarifications` | 0–2 | 1 |
| `connecting_message` | ≤ 120 chars, spoken in voice while the decision model runs | "One moment while I connect you." |
| `min_routing_accuracy` | 0.5–1, the routing suite's pass mark | 0.9 |
| `routing_mode` | `embedding` or `decision_model` (Routing mode, below) | `embedding` |
| `clear_win` | 0.5–0.99: Stage A's best score needed to route alone | 0.80 |
| `clear_margin` | 0–0.5: how far Stage A's best must lead the second | 0.10 |

# Decision

Input: the caller's text (for a clarified request, the original request and the answer), the scope, agents to exclude (a transfer excludes the requesting agent), and for a transfer the transferring agent's reason.

0. **Safety screen.** Before anything else, a caller line (the first line or a clarifying answer) that matches a safety phrase ([/architecture/escalation.md](/architecture/escalation.md)) is not routed: the supervisor is not asked and no embedding or decision-model request is made. The first segment opens at once on the scope's default agent, or on the Stage A leader when there is no default, with `method: safety`, and that agent's own safety rule answers the line: the fixed safety message in the caller's language, an escalation with category `safety`, the segment ends `handoff`. With no routable agent the conversation is refused as in step 1 ([CP-0042](/changes/cp-0042-safety-and-transfers-at-the-front-desk.md)).
1. **Candidates**: routable agents of the scope, minus exclusions. None → the conversation is refused (`no_routable_agents`, 409 at creation) or, on a transfer, escalated (below). One → it is chosen (`single`).
2. **Stage A — embedding.** Embed the input; score each candidate as the best cosine similarity over its catalog entries and, weighted × 0.85, its knowledge chunks. The shortlist is the top 5 with a score ≥ 0.35. A **clear win** is a best score ≥ `clear_win` (default 0.80) that leads the second by ≥ `clear_margin` (default 0.10).
3. **Decide by mode** (below): the embedding's clear win, or the decision model's answer with the embedding as fallback (`embedding` or `decision`).
4. **Unsure.** When the mode gives no agent and the conversation has asked fewer than `max_clarifications` questions, the front desk asks one, written by the [clarify prompt](/prompts/router-clarify.md) (`router` role) from the top two or three shortlisted profiles, and routes again on the answer (`clarified` when it then succeeds). When the answer still gives no agent but Stage A's leader is the same agent that led before the question, that agent is chosen (`clarified`, `decided_by: leader`), unless the answer is a plain negative ("no", "neither", "something else", "none of those") ([CP-0041](/changes/cp-0041-human-like-routed-conversations.md)). Otherwise it routes to the scope's default agent (`default`); with no default, the Stage A leader (`default`).
5. **Record** the decision on the conversation and emit `routing.decision` (topic `conversation:{id}`).
6. **Hand over the request.** The first segment's `meta.handoff` is `{reason: "Routed by the front desk", summary: <the caller's front-desk lines in order, joined with " / ", at most 500 chars>, routed: true}`; the agent's model also gets the front-desk lines as its history (`meta.history`), so it answers that whole request and a caller who answered a clarifying question with "Yes." is never asked what they wanted ([CP-0041](/changes/cp-0041-human-like-routed-conversations.md)).

In voice, the `connecting_message` is spoken when the decision model is asked and `routing.decision` ends it; the caller hears no silence longer than the message.

# Routing mode

| `routing_mode` | Decides | Falls back |
|---|---|---|
| `embedding` (default) | Stage A's clear win | no clear win → unsure (step 4); no decision model is ever called |
| `decision_model` | the decision model, given the shortlist (each agent's profile `summary`, plus an option `none`): a choice other than `none` at or above the threshold | to the `embedding` mode's result when the model is not configured, is blocked by PHI mode, fails (timeout, connection error, 429, 5xx, an answer naming no listed option) or is unsure; the reason is recorded in `fallbacks` (`not_configured`, `phi_mode`, `timeout`, `http_503`, `invalid_answer`, `unsure`) |

**Per-conversation override.** A playground conversation may carry its own `routing_mode` (`embedding` or `decision_model`, stored on the conversation); it replaces the front desk's `routing_mode` for every decision of that conversation (start, clarified and transfer) and is recorded as the decision's `mode`. Without one, the front desk's setting applies. Everything else is unchanged: a `decision_model` override on a server with no decision model, or one blocked by PHI mode, falls back to the embedding with the usual `fallbacks` reason (RTE-13, RTE-04). The public API does not accept it ([CP-0044](/changes/cp-0044-routing-mode-switch.md)).

The record's `method` names what decided (`embedding`, `decision`, `single`, `clarified`, `default`, `safety`) and `mode` the mode in force. The [routing suite](/architecture/capability-catalog.md) can compare both modes on the same cases.

# Decision model

One decision model, any server that speaks Jev's wire format (TypeSafe's hosted Jev, or a compatible server), configured by environment; nothing in the platform names a vendor.

| Variable | Meaning | Default |
|---|---|---|
| `DECISION_MODEL_URL` | base URL; requests go to `POST {url}/v1/systemone` | unset = not configured |
| `DECISION_MODEL_API_KEY` | sent as `Authorization: Bearer` when set | unset |
| `DECISION_MODEL_NAME` | the request's `model` field, e.g. `jev-latest` | unset (field omitted) |
| `DECISION_MODEL_THRESHOLD` | confidence needed; a front desk's `min_confidence` overrides it | 0.55 |
| `DECISION_MODEL_HOSTED` | `1` when a third party runs it, so `PHI_MODE` blocks it | `1` |
| `DECISION_MODEL_TIMEOUT_VOICE_MS` | time budget for one request in voice (start, clarified and transfer decisions); 100–5000, out of range → nearest bound, not a number → default | 350 |
| `DECISION_MODEL_TIMEOUT_TEXT_MS` | the same in text, the API, playground text and the routing suite | 1500 |

* Request: `{model?, state, questions: {route: {type: "choice", instructions, criteria: {<agent_id>: <summary>, none: "…"}}}}`; criteria are always label → description objects. The answer's `choice` is used; the confidence is `x_jev_confidence` when present, else `confidence` (some compatible servers report an entropy-based `confidence` on another scale); `probabilities` are recorded.
* Timeouts: `DECISION_MODEL_TIMEOUT_VOICE_MS` in voice and `DECISION_MODEL_TIMEOUT_TEXT_MS` in text ([CP-0029](/changes/cp-0029-configurable-decision-model-timeouts.md)). When the budget runs out the request is abandoned and the embedding decides (`fallbacks: timeout`); a connection error fails at once. For a hosted model measured at about 550 ms ([/verification/spikes.md](/verification/spikes.md) S5) a voice budget of 1000 ms is recommended: the caller hears the `connecting_message` meanwhile.
* **`PHI_MODE`** (`1` or `0`; default `1` when the process runs on Cloud Run, `0` otherwise): when on, a hosted decision model is never called and routing uses the embedding (`fallbacks: phi_mode`). Turn it off only for synthetic data until the provider has signed a BAA.
* `GET /healthz` reports `router: {decision_model: {configured, hosted, blocked, timeouts_ms: {voice, text}}}` (`blocked` = hosted and PHI mode on), with no network call.
* Measured 2026-11-01: a local Laya server was too slow and never confident ([/verification/spikes.md](/verification/spikes.md) S5) and was dropped; hosted Jev decided far more requests than the embedding at p50 about 550 ms (S5), which led to the configurable voice budget.

# Phone numbers

A phone number targets either an agent (as today) or the **front desk** (`phone_numbers.target: front_desk`, no agent), which starts a phone conversation with scope `member` ([/architecture/telephony.md](/architecture/telephony.md)). The IVR context of the call is part of the first routing input.

# Playground

Test call gains a **Full flow** mode next to **Single agent** ([/ui/test-call.md](/ui/test-call.md)): it creates a playground conversation through `POST /api/conversations` (scope chosen on the page) in text or voice and shows the **routing trace**: candidates and Stage A scores, whether Stage B ran and on which target, failovers, confidence, the clarifying question, the chosen agent and, later, each transfer with its reason.

# Routing record

Each decision in `conversations.routing`: `{at, trigger: start|clarified|transfer, input, scope, excluded, candidates: [{agent_id, score}], stage_a_ms, stage_b: {target, model, choice, confidence, probabilities, ms} | null, fallbacks: [{target, error}], method: explicit|single|embedding|decision|llm|clarified|default|transfer, agent_id, confidence, reason, clarification}`. The chosen segment's call stores `meta.routing` (method, confidence) and `routed_by`.

# Acceptance

- **RTE-01** — Given the seeded member scope and the utterance "I need to get treatment for my knee approved", when a conversation is routed, then Stage A chooses Claims & Pre-authorisation without a Stage B request and the decision records `method: embedding` with candidates and scores.
- **RTE-02** — Given `routing_mode: decision_model` and a configured decision model, when a request is routed, then the model receives the shortlisted agents' summaries and a `none` option (with `Authorization: Bearer` when a key is set and the configured `model` name), and an answer at or above the threshold routes with `method: decision` even when Stage A has a clear winner.
- **RTE-03** — Given `routing_mode: decision_model` and a decision model that times out, answers 503, names no listed option or answers `none`, then the embedding decides (its clear win routes with `method: embedding`, else the request is unsure) and the record lists the fallback with its reason.
- **RTE-04** — Given `PHI_MODE=1` and a hosted decision model, then no request reaches it and routing records `fallbacks: phi_mode`; given `DECISION_MODEL_HOSTED=0`, the model is called.
- **RTE-05** — Given a decision below the threshold and `max_clarifications: 1`, then the front desk asks one clarifying question naming the shortlisted areas, routes again on the answer, and a second unsure answer routes to the default agent; with `max_clarifications: 0` it routes to the default agent at once.
- **RTE-06** — Given a `staff` scope, then only internal agents are candidates; given a `member` scope, only inbound agents; an outbound agent is never a candidate.
- **RTE-07** — Given a routed voice conversation, then the front desk's greeting and disclosure are spoken first, the chosen agent's first line is its intro followed by its answer to the routed request (all the caller's front-desk lines, RTE-20), the voice does not change, and the first segment's transcript starts with the front-desk lines.
- **RTE-08** — Given a phone number with target `front_desk`, when it is called, then a phone conversation with scope `member` is created, the front desk answers, and the routed agent's segment carries the call's telephony and IVR context.
- **RTE-09** — Given a playground full-flow conversation, then every routing decision is emitted as `routing.decision` on topic `conversation:{id}` with candidates, Stage A scores, the decision model's answer and confidence, failovers and the chosen agent.
- **RTE-10** — Given a conversation created with `agent_id`, then no routing request is made and the decision records `method: explicit`.
- **RTE-11** — Given `GET /healthz`, then `router.decision_model` reports whether a decision model is configured, whether it is hosted and whether PHI mode blocks it, without network calls.
- **RTE-12** — Given `routing_mode: embedding` (the default), then no decision-model request is made: a clear win routes with `method: embedding` and anything else is unsure (clarifying question, then the default agent).
- **RTE-13** — Given `routing_mode: decision_model` and no `DECISION_MODEL_URL`, then routing behaves exactly as in `embedding` mode and records `fallbacks: not_configured`.
- **RTE-14** — Given `clear_win: 0.6` and `clear_margin: 0.02`, when Stage A's best is 0.65 and the second 0.62, then in `embedding` mode the best routes; with the defaults the same scores are unsure.
- **RTE-15** — Given a tenant that switches `routing_mode` in Settings, then the next routed request uses the new mode with no restart, and the record carries `mode`.
- **RTE-16** — Given `routing_mode: decision_model` and a decision model that answers in 600 ms, when a voice conversation is routed with `DECISION_MODEL_TIMEOUT_VOICE_MS=1000`, then the model's answer routes (`method: decision`); with the default (350) the same request records `fallbacks: timeout` and the embedding decides. The text budget is applied to text routing and the routing suite independently.
- **RTE-17** — Given `DECISION_MODEL_TIMEOUT_VOICE_MS` set to `50`, `99999` or `abc`, then the budget in force is 100, 5000 or 350 respectively, and `GET /healthz` reports `router.decision_model.timeouts_ms` with the budgets in force, without network calls.
- **RTE-18** — Given the member scope, `max_clarifications: 1` and Stage A results where Claims & Pre-authorisation leads with 0.815 against 0.719 (unsure), when the caller answers the clarifying question with "Yes." and Stage A again ranks Claims & Pre-authorisation first below `clear_win`, then the conversation routes to Claims & Pre-authorisation with `method: clarified` and `decided_by: leader`, not to the default agent.
- **RTE-19** — Given the same first decision, when the caller answers "No, something else", or a different agent now leads, then an unsure result routes to the default agent as before (`method: default`).
- **RTE-20** — Given a routed conversation whose front-desk caller lines are "I'm waiting to hear if my shoulder operation has been approved." and "Yes.", then the first segment's `meta.handoff` is `{reason: "Routed by the front desk", summary: "I'm waiting to hear if my shoulder operation has been approved. / Yes.", routed: true}`, the agent's system prompt contains that summary in its handoff block, and its model's first request carries the front-desk exchange (the greeting, the request, the clarifying question) as history before the caller's "Yes.", so it answers the whole request; the transcript still records the caller's line as "Yes.".
- **RTE-22** — Given a front desk with `routing_mode: embedding` and a configured decision model, when a playground conversation is created with `routing_mode: decision_model`, then its decisions are made by the decision model (`mode: decision_model`, `method: decision`); given the front desk on `decision_model` and a conversation created with `routing_mode: embedding`, then no decision-model request is made for it; given no override, the front desk's setting applies; a value other than the two modes is rejected with 422 `invalid_routing_mode`, and the public `/v1/conversations` ignores the field.
- **RTE-21** — Given a member-scope Full-flow conversation whose first caller line (or clarifying answer) contains a safety phrase such as "I have chest pain and I can't breathe", then no decision-model or embedding routing request is made for that line, the routing record has `method: safety`, the first segment opens on the scope's default agent (or the Stage A leader without a default), its first agent message is the safety message, an escalation with category `safety` exists and the segment ends `handoff`; for a line in Devanagari the Hindi safety message is used ([CP-0042](/changes/cp-0042-safety-and-transfers-at-the-front-desk.md)).
