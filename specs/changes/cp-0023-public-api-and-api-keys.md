---
type: Change Proposal
title: CP-0023 Public API, API keys and webhooks
description: A versioned /v1 API per tenant for server-to-server use - hashed, scoped API keys from Settings, conversations over text (JSON or SSE) and voice (WebSocket and Twilio-format media stream with single-use connect tokens), per-key rate limits, and signed webhooks.
status: stable
cp_state: implemented
tags: [api, security, voice, webhooks, tenancy]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

Tenants' agents run on the platform but can only be reached from the Studio (no authentication, a tenant switcher) or one phone number per agent. A tenant wants its own backend (member app, IVR, CRM) to start conversations with its agents. That needs authentication for the first time, a stable contract, and the voice-session pattern every voice-agent platform uses. First of five CPs in [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md), from the design session of 2026-11-01 (decisions Q1–Q33).

# What changes

* **API keys** in Settings → API keys: name, scope (`member` or `staff`), request limit (default 120/min) and concurrent-voice limit (default 10). The key is shown once and stored as a SHA-256 hash; keys list by prefix with last use; revoke takes effect at once.
* **`/v1/tenants/{tenant_id}/…`** authenticated with `Authorization: Bearer`. The key decides the tenant; a different path tenant answers 404 like an unknown tenant. Scope limits which agents are reachable; outbound agents never are.
* **Conversations** (new entity): create, message, end, get. In this CP a conversation has one segment and needs `agent_id`; routing (CP-0025) makes it optional and transfers (CP-0026) add segments.
* **Text** turns answer JSON, or stream SSE with `Accept: text/event-stream`.
* **Voice**: creating returns `connect: {url, token, expires_at}`; the token is single-use, bound to tenant, conversation and transport, valid 120 s, sent as a header or WebSocket subprotocol (never the query string). Transports: our WebSocket voice protocol and a Twilio-format **media stream** for any carrier (μ-law 8 kHz or PCM 16 kHz).
* **Rate limits**: 429 `rate_limited` with `Retry-After`; 429 `voice_capacity`.
* **Webhooks** in Settings → Webhooks: up to 5 endpoints, events started / transferred / escalated / ended / analyzed, signed `X-VoiceAI-Signature` with a timestamp, retried 7 times over about 9 hours, delivery log with resend, IDs only unless the endpoint opts into transcripts.
* New secret `PUBLIC_API_SECRET` (connect tokens).

# Affected specs

* New: [/api/public-api.md](/api/public-api.md) (PUB-01…PUB-10), [/architecture/webhooks.md](/architecture/webhooks.md) (WH-01…WH-05), [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).
* [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) - `/v1` resolution by key, isolation rules 9–10 (MT-14, MT-15).
* [/api/rest-api.md](/api/rest-api.md) - `/api/api-keys`, `/api/webhooks`, internal `/api/conversations` (API-10, API-12).
* [/api/voice-protocol.md](/api/voice-protocol.md) - the `/v1/voice` endpoint and token presentation, close code 4401.
* [/data/data-model.md](/data/data-model.md) - `api_keys`, `conversations`, `webhook_endpoints`, `webhook_deliveries`; `calls.conversation_id`, `calls.segment`, `calls.routed_by` (DM-10).
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md), [/api/events.md](/api/events.md) - `deliver_webhook`, topic `conversation:{id}`.
* [/architecture/deployment.md](/architecture/deployment.md) - `PUBLIC_API_SECRET`, `/healthz` (DEP-05).
* [/ui/settings.md](/ui/settings.md) - API keys and Webhooks cards (UI-56, UI-57).
* [/product/scope.md](/product/scope.md), [/product/healthcare-compliance.md](/product/healthcare-compliance.md) (rule 11), [/product/glossary.md](/product/glossary.md), [/process/conventions.md](/process/conventions.md) (prefixes `PUB`, `WH`).

# Acceptance criteria

New: PUB-01…PUB-10, WH-01…WH-05, MT-14, MT-15, API-10, API-12, DM-10, DEP-05, UI-56, UI-57. PUB-03 and PUB-05 are written for the routed API; until CP-0025 lands they hold with `agent_id` given. Each is written in its spec.

# Tasks

1. Spec edits (this CP).
2. Data: the four tables and the call columns, created on start for existing databases (DM-10).
3. `voiceai/public/keys.py`: key generation, hashing, prefix, lookup with revocation, `last_used_at` throttle; `/api/api-keys` routes — PUB-01, PUB-02, API-10.
4. `voiceai/public/auth.py`: the `/v1` dependency (key → tenant, path check, scope), request-id, rate limiter — PUB-02…PUB-04, MT-14.
5. `voiceai/conversations.py`: create (one segment on the given agent), message, end, view; the internal `/api/conversations` used by the playground — PUB-05, PUB-09, PUB-10, API-12, MT-15.
6. SSE turn streaming over the session's existing deltas — PUB-06.
7. Connect tokens (`PUBLIC_API_SECRET`, single use) and `WS /v1/voice/{id}` reusing `voice_calls.serve` — PUB-07.
8. `WS /v1/media-stream/{id}` reusing the Twilio serializer with negotiable format — PUB-08.
9. Webhooks: endpoints CRUD with encrypted secrets, rotation, event fan-out from conversation lifecycle, `deliver_webhook` with its own retry schedule, resend, 30-day purge — WH-01…WH-05.
10. Web: Settings API keys and Webhooks cards — UI-56, UI-57.
11. Tests for every ID above; `scripts/acceptance-baseline.txt` only for UI IDs, with approval.

# Risks and rollout

* First authentication in the product: keys are machine credentials only; the Studio is still unauthenticated, so anyone with Studio access can create keys (as with the OpenAI key today). Recorded in scope.
* Rate limits and used-token sets are in process; a second instance would weaken both ([/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)).
* Webhook URLs are tenant-supplied: requests go out with a 10 s timeout, no redirects, `https` only in the cloud. Private-network targets are not blocked in v1 (SSRF risk accepted for the pilot, listed as a production gap).
* No migration tool: new tables and columns are added on start like CP-0021.

# Out of scope

SIP; OAuth or per-user tokens; client-side (browser) keys; per-key IP allowlists; webhooks for Studio or phone conversations; usage billing per key.
