---
type: Decision Record
title: ADR-0012 Public tenant API and supervisor routing
description: A versioned server-to-server API per tenant authenticated by hashed, scoped API keys; a supervisor that routes each conversation to the right agent from an automatically synced capability catalog with a two-stage decision (embeddings, then a swappable decision model); agent-to-agent transfer inside one conversation. Records the research and the plan across CP-0023…CP-0027.
status: stable
tags: [decision, api, routing, security, voice]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Context

A tenant has several specialist agents (claims, coverage, policy, internal knowledge). Today they can be reached only from the Studio (tenant switcher, no authentication) or a phone number tied to exactly one agent. Tenants want to invoke them from their own systems, and their systems do not know which agent should handle a request: "it is about a claim" should reach the claims agent, "what does my plan cover" the coverage agent, without the tenant maintaining a routing table, because agents gain use cases, knowledge and tools all the time.

What existed on 2026-11-01 (code map of the same day):

* Tenant from `X-Tenant-Id` only ([/architecture/multi-tenancy.md](/architecture/multi-tenancy.md)); authentication is out of scope ([/product/scope.md](/product/scope.md)).
* A call is bound to one agent and one version; escalation, memory, scoring, analysis and test suites all key off that binding. No entity spans calls.
* The text and cascade loops re-read prompt and tools every model round; the realtime bridge already re-sends `session.update` mid-call (after verification). The realtime provider does not change the voice after audio has played.
* `use_cases` (category, title, summary, sample utterances per agent) exist but are seed-only; `agents.description` is not in the version snapshot.
* Embeddings: local `bge-small-en-v1.5`, in-process NumPy search ([/decisions/adr-0004-storage-and-vectors.md](/decisions/adr-0004-storage-and-vectors.md)). The gateway speaks only OpenAI-compatible chat.

Research (2026-11-01, primary sources; vendor figures are self-reported unless noted):

* **Starting voice sessions.** Vapi, Retell, ElevenLabs, OpenAI Realtime, LiveKit, Deepgram, Pipecat Cloud and Gemini Live share one pattern: the customer's server creates the session with a secret key and receives a short-lived, scoped client credential (ephemeral key, signed URL, room token; 30 s–15 min, often single-use, valid only to *start*); the client connects over WebSocket or WebRTC; phone and SIP are separate entry points; lifecycle is reported by signed webhooks ending in an end-of-call report, mirrored by GET. https://docs.vapi.ai/calls/websocket-transport · https://docs.retellai.com/api-references/create-web-call · https://elevenlabs.io/docs/agents-platform/customization/authentication · https://developers.openai.com/api/docs/guides/voice-webrtc · https://docs.livekit.io/frontends/authentication/tokens/ · https://developers.deepgram.com/reference/auth/tokens/grant · https://docs.pipecat.ai/deployment/pipecat-cloud/rest-reference/endpoint/start · https://ai.google.dev/gemini-api/docs/ephemeral-tokens · https://elevenlabs.io/docs/agents-platform/workflows/post-call-webhooks
* **Bring your own carrier.** Twilio Media Streams' frame format (μ-law 8 kHz JSON events) is emitted by most carriers and contact-center platforms; ElevenLabs and Vapi accept it. https://www.twilio.com/docs/voice/conversationrelay/websocket-messages
* **Routing models.** Embedding match (aurelio-labs semantic-router, MIT) is fast but weak on vague and multi-intent turns. Decision models score a fixed set of options in one pass: TypeSafe **Jev** (hosted, closed, `jev-1.14.0` of 2026-10-14, $0.042 per 1M input tokens, output free, early access, no published HIPAA/BAA terms) and **Laya** (Apache-2.0, ModernBERT-large 421M / mmBERT-base 322M, `pip install laya[serve]` serves Jev's wire format; Ollaya serves it too). Katanemo Plano-Orchestrator-4B is purpose-built for agent routing but needs a GPU and a research-tagged licence. LLM handoffs (OpenAI Agents SDK, Google ADK `transfer_to_agent`) are accurate and multi-turn but cost a full LLM turn. https://typesafe.ai/blog/introducing-system-one-models-and-jev · https://docs.typesafe.ai/models.md · https://github.com/NandhaKishorM/laya · https://github.com/ollaya-dev/ollaya · https://github.com/aurelio-labs/semantic-router · https://huggingface.co/katanemo/Plano-Orchestrator-4B · https://arxiv.org/abs/2506.16655
* **Capability descriptions.** A2A AgentCard skills carry `name`, `description`, `tags` and `examples`, a standard shape for both descriptions (for decision models) and example utterances (for embeddings). https://a2a-protocol.org/latest/specification/
* **Cost of self-hosting Laya** (us-central1, 30 days, to be re-checked): a separate CPU Cloud Run service (2 vCPU, 4 GiB, min 1) ≈ $115/month; in-process ≈ $67/month extra; an L4 GPU ≈ $750/month; Jev at 10k decisions/day ≈ $4/month. CPU latency on 2–4 vCPU is unpublished.

# Options

1. **Routing config per tenant** (intents → agents). Rejected by the product owner: does not scale as agents change.
2. **Supervisor agent in every turn** (agents as tools of a supervisor LLM). One extra model call per turn, too slow for voice, and blurs which agent is scored and learns.
3. **One merged agent.** Loses per-agent prompts, tools, evaluation and self-learning.
4. **Supervisor at the edges** (route at the start and on transfer only), from a catalog built automatically from what agents already have, with a cheap first stage and a swappable decision model.

# Decision

Option 4.

1. **Public API.** `/v1/tenants/{tenant_id}/…`, server to server. A per-tenant **API key** (Settings → API keys, shown once, stored as a SHA-256 hash, revocable) decides the tenant; a path tenant that differs answers 404 exactly like an unknown tenant. Keys carry a **scope**: `member` routes only to inbound agents, `staff` only to internal agents; outbound agents are never routable. Per-key rate limits. The Studio itself keeps the tenant switcher ([/api/public-api.md](/api/public-api.md)).
2. **Industry-standard voice start.** Creating a voice conversation returns a URL and a single-use token bound to tenant, conversation and transport, valid 120 s to connect, presented in a header or WebSocket subprotocol, never the tenant key. Transports: our WebSocket protocol, a Twilio-format media stream for any carrier, and WebRTC (CP-0027). SIP is deferred.
3. **Conversation.** A new entity spans one call per agent segment. The caller's connection stays; segments keep today's per-call scoring, escalation and memory unchanged.
4. **Capability catalog.** Each published, routable agent gets a profile (description, use cases with utterances, tools, knowledge, generated examples), re-indexed in the background on publish and on use-case and knowledge changes ([/architecture/capability-catalog.md](/architecture/capability-catalog.md)).
5. **Two-stage routing** (superseded by [CP-0028](/changes/cp-0028-routing-strategies-and-local-laya.md): the embedding decides by default; one optional Jev-compatible decision model replaces the Jev/Laya/LLM targets). Stage A: the existing embedder over the catalog shortlists agents and routes alone when one clearly wins. Stage B: a decision model picks among the shortlist with a confidence. One Jev-format client serves two decision targets, hosted **Jev** and self-hosted **Laya**, selected by `ROUTER_DECISION_TARGET`; an LLM router through the gateway (`router` role) is the third target and the universal fallback. Failover per decision on timeout or error. **`PHI_MODE`** forbids the hosted target, as primary and as fallback, until a BAA exists ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)).
6. **Clarify, then default.** Below the confidence threshold the front desk asks up to `max_clarifications` questions (LLM-written), then routes to the scope's default agent.
7. **Transfer.** A built-in `transfer_to_agent` lets an agent say "not mine"; the supervisor picks the next agent. Verification, member reference, call context and the transferring agent's summary carry over; memory stays per agent; one voice and one pipeline per conversation; at most 3 transfers ([/architecture/agent-transfer.md](/architecture/agent-transfer.md)).
8. **Evaluated like everything else.** Every routing decision is recorded and traced; misroutes become scorecard checks and learning signals; a tenant-level routing suite (utterance → expected agent) runs after every re-index; nightly learning may propose catalog fixes that a human approves.
9. **Webhooks** report conversation lifecycle, signed and retried, IDs-only by default because transcripts carry PHI ([/architecture/webhooks.md](/architecture/webhooks.md)).

# Plan

| CP | Content |
|---|---|
| [CP-0023](/changes/cp-0023-public-api-and-api-keys.md) | API keys, the `/v1` API for text and WebSocket voice, media stream, rate limits, webhooks |
| [CP-0024](/changes/cp-0024-capability-catalog.md) | Use-case editing, description in the snapshot, capability profiles, re-index job, routing suite |
| [CP-0025](/changes/cp-0025-supervisor-routing.md) | Front desk and two-stage routing, decision targets with failover and `PHI_MODE`, clarification, phone numbers to the front desk, full-flow playground and routing trace, Laya spike |
| [CP-0026](/changes/cp-0026-agent-transfer.md) | `transfer_to_agent`, conversation segments, carry-over, transfer limit, misroute scoring and learning |
| [CP-0027](/changes/cp-0027-webrtc-transport.md) | WebRTC transport |

All five ship in one release; each ships its own specs and code.

# Consequences

* Authentication enters the product for the first time, limited to machine keys on `/v1`. Studio login, SSO and RBAC stay out of scope.
* A routed conversation may involve several agent versions; dashboards count conversations once (the last segment carries the outcome).
* The router adds a dependency (Jev or Laya). The LLM fallback keeps routing working when it is down; the routing suite measures whether a target is good enough before it becomes the default.
* Single-instance limits ([/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)) apply to rate limits and single-use tokens, which are held in process.
* WebRTC on Cloud Run needs a TURN relay because Cloud Run accepts no inbound UDP (CP-0027).
