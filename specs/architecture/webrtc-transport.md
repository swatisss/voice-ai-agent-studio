---
type: Component Spec
title: WebRTC transport
description: WebRTC as a third voice transport of the public API and the playground - SDP offer/answer over HTTPS with a connect token, ICE and TURN on Cloud Run, Opus audio into the same pipelines.
status: stable
tags: [architecture, voice, webrtc, public-api]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Purpose

Browser and mobile clients expect WebRTC: it handles jitter, NAT traversal and echo cancellation, and every major voice-agent vendor offers it ([ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md)). It is a transport only: the conversation, supervisor, agents and pipelines are the same as over the [voice WebSocket](/api/voice-protocol.md).

# Connect

1. `POST /v1/tenants/{t}/conversations` with `channel: voice, transport: webrtc` returns `connect: {offer_url, token, expires_at, ice_servers}` ([/api/public-api.md](/api/public-api.md)). `offer_url` is `https://{host}/v1/webrtc/{conversation_id}/offer`.
2. The client creates an `RTCPeerConnection` with `ice_servers`, adds one audio track, creates an offer and POSTs `{sdp, type: "offer"}` to `offer_url` with `Authorization: Bearer <token>` within 120 s. The token is single-use, as for WebSocket voice.
3. The server answers `{sdp, type: "answer"}` (Pipecat's small WebRTC transport, inside `voiceai/voice/`), ICE completes, and the front desk or agent speaks first.
4. A data channel `control` carries the voice protocol's JSON messages (`ready`, `interrupt`, `end`, `hangup`).

Audio is Opus in both directions; the pipeline resamples as for other transports. Barge-in stops server-side playout; the client needs no `interrupt` handling for audio already queued in the jitter buffer, but MUST honour `end`.

# ICE and TURN

Cloud Run accepts no inbound UDP, so media must go through a TURN relay reachable over TCP/TLS 443 by both the client and the service.

| Setting | Meaning |
|---|---|
| `WEBRTC_STUN_URLS` | default `stun:stun.l.google.com:19302` |
| `WEBRTC_TURN_URLS`, `WEBRTC_TURN_USERNAME`, `WEBRTC_TURN_CREDENTIAL` | a TURN service (for example a managed one); on Cloud Run required for `webrtc`, else creation returns 503 `webrtc_unavailable` |

`ice_servers` returned to the client carry the STUN URLs and, when set, TURN with short-lived credentials (the configured static credential is never returned when the provider supports time-limited ones; otherwise it is returned, which the deployment runbook records as a known risk). `/healthz` reports `webrtc: bool` (TURN configured or not on Cloud Run).

# Acceptance

- **WRTC-01** — Given a `webrtc` voice conversation, when a client posts a valid SDP offer with the token, then the response is an SDP answer, audio flows after ICE completes, the front desk's welcome is heard first, and the conversation behaves as over WebSocket (routing, transfer, end reasons).
- **WRTC-02** — Given an offer with a used, expired or other conversation's token, then the response is 401 and no peer connection is created.
- **WRTC-03** — Given the process on Cloud Run without `WEBRTC_TURN_URLS`, then creating a `webrtc` conversation returns 503 `webrtc_unavailable` and `/healthz` reports `webrtc: false`.
- **WRTC-04** — Given the data channel, then `hangup` from the client ends the conversation with reason `hangup` and the server sends `end` with the reason before closing.
