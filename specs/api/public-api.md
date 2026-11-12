---
type: API Contract
title: Public API (v1)
description: The server-to-server API a tenant's backend uses to start and run conversations with its agents - API keys and scopes, conversations over text and voice, connect tokens, transports, streaming, rate limits and errors.
status: stable
tags: [api, public, security, voice]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Purpose

A tenant's own systems (a member app backend, an IVR, a CRM) talk to the tenant's agents without knowing which agent handles what: the [supervisor](/architecture/supervisor-routing.md) routes each conversation. The Studio keeps using `/api/*` with the tenant switcher ([/api/rest-api.md](/api/rest-api.md)); `/v1/*` is the only surface that accepts API keys. Decision record: [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).

# API keys

| Field | Rules |
|---|---|
| `name` | 1–60 chars, unique per tenant |
| `scope` | `member` (routes to `inbound` agents) or `staff` (routes to `internal` agents); outbound agents are never reachable |
| `rate_limit_per_min` | 10–6000, default 120 |
| `max_concurrent_voice` | 0–200, default 10 |

* Format: `vak_` followed by 40 random base62 characters (≥ 230 bits). The full key is returned **once**, by the create call; the platform stores its SHA-256 hash and the first 12 characters (`prefix`) for display. A key cannot be shown again.
* Sent as `Authorization: Bearer <key>` on every `/v1` request.
* A tenant has at most 20 active keys. Revoking (`DELETE`) sets `revoked_at`; the key fails from the next request. `last_used_at` is updated at most once a minute.
* Managed from Settings → API keys ([/ui/settings.md](/ui/settings.md)) through `GET/POST /api/api-keys`, `PUT/DELETE /api/api-keys/{id}` ([/api/rest-api.md](/api/rest-api.md)).

# Tenant resolution and errors

* The key decides the tenant. `{tenant_id}` in the path MUST equal the key's tenant; otherwise the response is 404 `tenant_not_found`, identical to an unknown tenant ([/architecture/multi-tenancy.md](/architecture/multi-tenancy.md)).
* Missing, malformed, unknown or revoked key → 401 `invalid_key` (`WWW-Authenticate: Bearer`). The body never says which.
* Errors use the platform shape `{"error", "detail"}`. Objects of another tenant, or agents outside the key's scope, are 404.
* `X-Request-Id` is echoed when sent, else generated, and logged with the key prefix (never the key).

# Rate limits

Per key, in process (single instance, [/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)):

* **Requests**: a sliding 60 s window over every `/v1` HTTP request of the key. Over the limit → 429 `rate_limited` with `Retry-After` (seconds) and `X-RateLimit-Limit`, `X-RateLimit-Remaining`.
* **Concurrent voice**: active voice conversations created with the key. Creating one more → 429 `voice_capacity`.

# Endpoints

Base: `/v1/tenants/{tenant_id}`. JSON in and out, `snake_case`, ISO 8601 UTC.

| Method | Path | Body → Result |
|---|---|---|
| GET | `/agents` | → `{items: [{id, name, description}]}`: the published, routable agents in the key's scope |
| POST | `/conversations` | create (below) |
| POST | `/conversations/{id}/messages` | `{text}` (1–2000 chars) → turn result (below); text conversations only, else 409 `wrong_channel` |
| POST | `/conversations/{id}/end` | → `{status, outcome}`; idempotent |
| GET | `/conversations/{id}` | query `include=transcript` → conversation view (below) |

## Create a conversation

```json
{ "channel": "text", "message": "I want to check on a claim", "agent_id": null,
  "transport": null, "audio_format": null,
  "caller": { "number": "+447700900142" }, "context": { "ivr_menu": "claims" },
  "metadata": { "crm_case": "48213" }, "external_id": "case-48213" }
```

| Field | Rules |
|---|---|
| `channel` | `text` or `voice` |
| `message` | text only, optional: the caller's first utterance; routing runs on it immediately |
| `agent_id` | optional: skip routing; the agent must be published, in scope and not outbound, else 404 `agent_not_found` |
| `transport` | voice only: `websocket` (default), `media-stream`, `webrtc` ([/architecture/webrtc-transport.md](/architecture/webrtc-transport.md)) |
| `audio_format` | `media-stream` only: `mulaw_8k` (default) or `pcm_16k` |
| `caller.number` | optional E.164; identifies the caller exactly like a phone call's number ([/architecture/caller-verification.md](/architecture/caller-verification.md)); only the identification result is kept |
| `context` | ≤ 10 entries, keys `^[a-z][a-z0-9_]{0,30}$`, values ≤ 200 chars; become call context lines like IVR context and never mark the caller verified |
| `metadata` | JSON object ≤ 4 KB, stored and echoed in views and webhooks, never shown to the agent |
| `external_id` | ≤ 128 chars, echoed |

Text result (201):

```json
{ "conversation_id": "…", "status": "active", "channel": "text",
  "agent": { "id": "…", "name": "Claims & Pre-authorisation" },
  "routing": { "method": "embedding", "confidence": 0.91, "reason": "…" },
  "messages": [ { "speaker": "front_desk", "text": "Thanks for calling Northgate Health, this is Olivia. I'm a virtual assistant…" },
                { "speaker": "agent", "agent_id": "…", "text": "You're now with our claims and treatment team. I can help with that…" } ] }
```

* Without `message` (and without `agent_id`) only the front-desk greeting and disclosure come back; `agent` and `routing` are `null` until the first message is routed.
* With `agent_id`, the first message is that agent's greeting (or its reply, when `message` is given), as for a Studio call.
* When the front desk asks a clarifying question, `agent` stays `null` and the question is the last message.

Voice result (201): `{conversation_id, status, channel: "voice", transport, connect: {url, token, expires_at, protocol}}` (WebRTC adds `offer_url` and `ice_servers`, CP-0027). The front desk (or the chosen agent) speaks first once the client connects.

## Turn result

`{conversation_id, status, agent, routing, messages, transferred, escalation, ended}`: `messages` lists what was said since the caller's message (a transfer adds the receiving agent's intro line); `routing` is present when this turn routed or re-routed; `transferred` is a boolean; `escalation` is `{id, status}` once the conversation is escalated; `status` is `active`, `escalated` or `ended`.

**Streaming.** With `Accept: text/event-stream` the same request streams server-sent events `message.delta` (`{speaker, agent_id, text}`), `routing.decision`, `conversation.transferred` and a final `turn.done` carrying the turn result.

## Conversation view

`{id, status, channel, transport, source, scope, external_id, metadata, started_at, ended_at, outcome, agent, segments: [{call_id, agent_id, agent_name, segment, routed_by, started_at, ended_at, outcome}], routing: [decision], escalation, transcript?}`. `transcript` (only with `include=transcript`) is the ordered caller, front-desk and agent lines with segment numbers; tool calls are not included.

# Voice connect

* `connect.url` is `wss://{host}/v1/voice/{conversation_id}` (`websocket`) or `wss://{host}/v1/media-stream/{conversation_id}` (`media-stream`). `{host}` comes from `PUBLIC_BASE_URL`.
* `connect.token` is single-use, bound to tenant, conversation and transport, valid **120 s** to open the socket (`expires_at`); the session then lasts up to the agent's maximum call length. It is an HMAC-SHA256 over those fields and the expiry, keyed with `PUBLIC_API_SECRET`; used tokens are remembered in process until they expire. Unset secret → voice creation returns 503 `voice_tokens_unavailable`.
* The token is presented as `Authorization: Bearer <token>` on the upgrade request, or, for clients that cannot set headers, as the WebSocket subprotocol `vai-token.<token>` next to `vai.voice.v1` (the server answers with `vai.voice.v1`). Query-string tokens are refused, so tokens stay out of access logs.
* `websocket` speaks the [voice protocol](/api/voice-protocol.md). `media-stream` speaks Twilio Media Streams JSON (`connected`, `start`, `media`, `mark`, `stop`, and `clear` back) in `mulaw_8k`, or the same events with base64 PCM 16 kHz in `pcm_16k` ([/architecture/telephony.md](/architecture/telephony.md)).
* Close codes as the voice protocol, plus `4401` bad, expired or used token.
* A voice conversation whose socket never connects within the token lifetime ends with reason `idle` and outcome `abandoned`.

# Acceptance

- **PUB-01** — Given a key created with `POST /api/api-keys`, then the response contains the full key once; the stored row holds only its SHA-256 hash and prefix; `GET /api/api-keys` lists the prefix, scope and limits and never the key; a request with the key to `/v1/tenants/{own tenant}/agents` succeeds and updates `last_used_at`.
- **PUB-02** — Given a key of tenant A, when it calls `/v1/tenants/{tenant B}/agents`, then the response is 404 `tenant_not_found` with the same body as for a tenant that does not exist; given no key, a malformed, unknown or revoked key, then the response is 401 `invalid_key`.
- **PUB-03** — Given a `member` key, then `GET /agents` lists only published routable inbound agents, and creating a conversation with an internal or outbound agent's `agent_id` is 404 `agent_not_found`; given a `staff` key, only internal agents are listed and reachable.
- **PUB-04** — Given a key with `rate_limit_per_min: 10`, when an 11th request arrives within 60 s, then it is answered 429 `rate_limited` with a `Retry-After` header; given `max_concurrent_voice: 1` and one active voice conversation, then creating another is 429 `voice_capacity`.
- **PUB-05** — Given a text conversation created with `message` "I want to check on a claim" on the seeded tenant, then the response has `status: active`, Claims & Pre-authorisation as `agent`, a `routing` object, and messages from the front desk (greeting with disclosure) and the agent; `POST /messages` continues with the same agent; `POST /end` returns the outcome and a second `POST /end` returns the same.
- **PUB-06** — Given `POST /messages` with `Accept: text/event-stream`, then the response streams `message.delta` events and ends with one `turn.done` whose payload equals the JSON turn result of the same turn.
- **PUB-07** — Given a voice conversation, then the result carries `connect.url` on `PUBLIC_BASE_URL`'s host, a token and `expires_at` 120 s ahead; the socket accepts the token in the `Authorization` header or as subprotocol `vai-token.<token>`; a second use, an expired token, a token of another conversation or a token in the query string closes with 4401 before any pipeline starts.
- **PUB-08** — Given a `media-stream` voice conversation and a client sending Twilio Media Streams events with μ-law audio, then the conversation runs like a phone call (welcome spoken after `start`, agent audio returned as `media` events with the `streamSid`, `stop` ends it with reason `hangup`); with `audio_format: pcm_16k`, the payloads are PCM 16 kHz.
- **PUB-09** — Given `caller.number` set to a registered demo number and `context` with `ivr_menu`, then the first segment's call is identified by first name only, its call context lists `ivr_menu`, and no response or stored row contains the full number; `metadata` and `external_id` are echoed by `GET /conversations/{id}`.
- **PUB-10** — Given `GET /conversations/{id}?include=transcript` after a transfer, then `segments` lists both calls in order with `routed_by`, and the transcript lists front-desk, caller and agent lines with their segment numbers and no tool calls.
