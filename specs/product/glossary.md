---
type: Glossary
title: Glossary
description: Shared vocabulary used across specs, code and UI labels.
status: stable
tags: [product, glossary]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

| Term | Meaning |
|---|---|
| **Tenant** | A business unit using the platform (e.g. *Northgate Health · Member & Sales Services*). All data is scoped to one tenant. |
| **Agent** | A configured AI agent: persona + policy + knowledge + tools + skills + model choice. Has an editable **draft** and published **versions**. |
| **Agent version** | Immutable snapshot of an agent's config. Every call records the version that handled it. |
| **Persona** | Name, voice, greeting, speaking style and disclosure line. |
| **Policy** | Rules, escalation conditions, things the agent must never do, max turns, handoff and holding messages. |
| **Tool** | A callable HTTP API with a JSON-schema parameter list (e.g. `get_claim_status`). |
| **Skill** | A plain-English procedure for one kind of request: when it applies, steps, which tools it uses, when to escalate. |
| **Knowledge article / doc** | A document the agent can search. Split into chunks and embedded. |
| **Call** | One conversation (channel `voice`, `text` or `simulation`). |
| **Scorecard** | The measures and check verdicts of one scored call, tied to the agent version that handled it ([/architecture/call-scoring.md](/architecture/call-scoring.md)). |
| **Check** | One yes/no question a call is scored on, decided in code or by the judge; built in, derived from the agent's policy, or custom. Verdicts: pass, fail, n/a, unknown, not judged. |
| **Hard gate** | A safety or compliance check whose failure fails the whole call (or, later, a run), whatever the other scores. |
| **Calibrated check** | A judge check with at least 20 human reviews agreeing with the judge at least 85 % of the time. |
| **Test scenario** | A situation an agent must handle: a simulated caller's goal, profile and persona, the expected outcome and the tools and results expected ([/architecture/test-suites.md](/architecture/test-suites.md)). |
| **Test run** | Every enabled scenario of an agent played k times against one config (published, draft or an earlier version), each simulated call scored. |
| **pass^k** | A scenario passes only if all k of its repeats pass; reported next to the pass rate because a single run hides flaky behaviour. |
| **Learning inbox** | The proposals drafted overnight or by hand that wait for a human decision, each with its gate result. |
| **Gate** | The offline check a proposal must pass before approval: lift on cluster and held-out cases, no regressed test scenario, no new hard fail, no slowdown. |
| **Held-out case** | A call from the cluster that the drafter never saw, used only to judge the fix. |
| **Drift** | A version's recent scores falling well below its own first week. |
| **Turn** | One caller utterance plus the agent's response. |
| **Containment** | A call resolved without a human. |
| **Escalation** | Handing a call to a human, with a reason category. |
| **Groundwork packet** | Structured handoff: summary, intent, entities, what was tried, reason, sentiment, suggested next action. |
| **Disposition** | The human's outcome code when closing an escalation. |
| **Call analysis** | Post-call structured judgment: outcome, intent, root cause, gap summary. |
| **Root cause** | Why a call was escalated: `missing_knowledge`, `missing_skill`, `tool_error`, `policy_required`, `safety`, `caller_requested`, `asr_error`, `agent_error`, `other`. |
| **Fixable** | Root causes the platform may propose a fix for: `missing_knowledge`, `missing_skill`, `agent_error`. |
| **Cluster** | A group of calls sharing a similar gap. Has a name, size, cost impact and status. |
| **Fix proposal** | A drafted change (knowledge article or skill + tool) for a cluster. |
| **Eval run** | Simulated replay of a cluster's cases plus regression scenarios against the current version (baseline) and the proposal (candidate), graded by a judge. |
| **Regression scenario** | A saved caller goal the agent already handles; must keep passing. |
| **Role (LLM)** | A job the LLM does: `realtime`, `analysis`, `drafting`, `simulator`, `judge`. Each maps to a provider + model. |
| **Use case** | A named support scenario (for example *Payments & Direct Debit*) linked to an agent, with sample utterances and demo callers ([/product/use-cases.md](/product/use-cases.md)). |
| **Call mode** | `inbound` (customer calls in), `outbound` (the agent places the call) or `internal` (staff-facing assistant) ([/architecture/call-modes.md](/architecture/call-modes.md)). |
| **Call context** | Facts about whom an outbound call is to (first name, policy, renewal details); never marks the callee as verified. |
| **Membership number** | A Northgate member's reference (`NGH-410237`); with the date of birth it verifies a caller. |
| **Excess** | The amount a member pays towards treatment before the insurer pays, once per person per policy year (for example £100). |
| **Shortfall** | The part of a specialist's or hospital's bill above the insurer's fee guidelines, which the member pays; a fee-assured specialist never leaves one. |
| **Fee-assured** | A specialist who has agreed to charge within the insurer's fee guidelines, so the member has no shortfall. |
| **Pre-authorisation** | The insurer's approval of a treatment before it happens, identified by a code (`PA-500955`) that lets the hospital bill the insurer directly. Surgery stays *pending* until the procedure code and fee estimate arrive. |
| **Open referral** | A GP referral to a type of specialist rather than a named one, so the insurer can suggest a specialist on the member's hospital list. |
| **Direct Access** | Getting treatment approved without seeing a GP first, for muscles, bones and joints, mental health, cancer symptoms and moles or skin lesions. |
| **Moratorium** | Underwriting without medical questions: conditions the member had in the 5 years before cover started are excluded until they have had 2 clear years. |
| **Full medical underwriting** | Underwriting where everyone answers medical questions up front; declared conditions become named personal exclusions; 5% cheaper in the demo. |
| **Switch** | Underwriting that keeps the terms of another UK insurer after at least 12 months of continuous cover. |
| **Hospital list** | The hospitals a policy can use (Essential, Extended, London Premium). |
| **Cash plan** | A separate low-cost plan that refunds everyday costs (dental, optical, therapies, consultations, hospital nights) up to yearly limits, claimed with a receipt. |
| **Cooling-off** | The 21 days after a new policy starts in which it can be cancelled with a full refund. |
| **Digital GP** | Video or phone appointments with a GP or nurse, included for anyone named on a health policy. |
| **Turn detection** | How the voice pipeline decides the caller has finished speaking: normal (silence) or semantic ([/architecture/turn-detection.md](/architecture/turn-detection.md)). |
| **Live controls** | Persona and turn-detection settings changed while a test call is running. |
| **OKF** | Open Knowledge Format — Markdown + YAML frontmatter bundle format used for these specs and importable as knowledge. |
| **IVR** | Interactive voice response: the phone menu in front of the agent that forwards a call to the agent's phone number and may pass context (`ivr_*`). |
| **Media Stream** | Twilio's feature that sends a live phone call's audio to our WebSocket and plays audio back ([/architecture/telephony.md](/architecture/telephony.md)). |
| **Voice pipeline** | How a voice call turns audio into answers: `cascade` (speech-to-text, brain, text-to-speech) or `realtime` (one speech-to-speech model) ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)). |
| **Transfer** | Redirecting a live phone call to a person's number after a hand-off. |
| **Identified caller** | A caller whose phone number is registered on a member's record; addressed by first name, not yet verified ([/architecture/caller-verification.md](/architecture/caller-verification.md)). |
| **Verified caller** | A caller who proved who they are in this call: registered number + date of birth, or member ID + date of birth. |
| **Member memory** | What one agent remembers about one verified member across calls: **episodes** (call summaries) and **facts** (preferences, relationships, commitments) ([/architecture/agent-memory.md](/architecture/agent-memory.md)). |
| **Supersede** | The agent replacing a remembered fact with a newer one; the old fact is retired, not deleted. |
| **Erase member** | Removing everything every agent remembers about a member; only a content-free record that it happened remains. |
| **API key** | A tenant's machine credential for the `/v1` public API, with a scope (`member` or `staff`) and limits; shown once, stored hashed ([/api/public-api.md](/api/public-api.md)). |
| **Conversation** | One caller connection that may pass through several agents; each agent's part is a **segment** (a call) ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)). |
| **Front desk** | What opens a routed conversation: a persona's greeting and disclosure, clarifying questions, the connecting message. |
| **Supervisor** | Picks the agent for a conversation at the start and on transfer; never takes part in an agent's turns. |
| **Capability profile** | What the supervisor knows about one agent: description, use cases, tools, knowledge titles, generated example requests ([/architecture/capability-catalog.md](/architecture/capability-catalog.md)). |
| **Decision model** | An optional Jev-compatible model the supervisor asks to pick the agent when the routing mode is `decision_model`; the embedding decides when it is not configured or unsure. |
| **PHI mode** | A switch that keeps caller text away from a hosted decision model without a BAA. |
| **Routing mode** | `embedding` (default) or `decision_model`: what picks the agent in the supervisor ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)). |
| **Agent transfer** | An agent handing a conversation to another agent through `transfer_to_agent` (not the phone **Transfer** to a person) ([/architecture/agent-transfer.md](/architecture/agent-transfer.md)). |
| **Routing suite** | The tenant's test of the router: utterances with the agent that should get them, run after every catalog change. |
| **Webhook** | A signed POST to a tenant's URL when an API conversation starts, transfers, escalates, ends or is scored ([/architecture/webhooks.md](/architecture/webhooks.md)). |
