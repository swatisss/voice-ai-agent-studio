---
type: Change Proposal
title: CP-0027 WebRTC transport
description: WebRTC as a third voice transport for public-API and playground conversations - SDP offer/answer with a single-use token, a control data channel, STUN and a TURN relay for Cloud Run.
status: stable
cp_state: implemented
tags: [voice, webrtc, api, deployment]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

The voice research of 2026-11-01 found WebRTC standard for browser and mobile clients at every major vendor; the product owner wants all channels in one release (Q31). Fifth CP of [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md); it changes transport only.

# What changes

* `transport: webrtc` on voice conversations returns an offer URL, a single-use token and ICE servers.
* The client posts its SDP offer; the server answers through Pipecat's small WebRTC transport; a `control` data channel carries the voice protocol's JSON messages.
* STUN by default; a TURN relay is required on Cloud Run (no inbound UDP); without it `webrtc` is unavailable (503) and `/healthz` says so.

# Affected specs

* New: [/architecture/webrtc-transport.md](/architecture/webrtc-transport.md) (WRTC-01…WRTC-04).
* [/api/public-api.md](/api/public-api.md) - `transport: webrtc` and its `connect` fields.
* [/api/voice-protocol.md](/api/voice-protocol.md) - the control channel uses the same messages.
* [/architecture/deployment.md](/architecture/deployment.md) - `WEBRTC_*` settings, `/healthz.webrtc`.
* [/product/scope.md](/product/scope.md), [/process/conventions.md](/process/conventions.md) (prefix `WRTC`).

# Acceptance criteria

New: WRTC-01…WRTC-04.

# Tasks

1. Spec edits (this CP).
2. Spike: Pipecat small WebRTC transport with a managed TURN service against a Cloud Run deployment; record in [/verification/spikes.md](/verification/spikes.md) as S6.
3. `POST /v1/webrtc/{id}/offer` with token check; transport wiring into `voice_calls.serve`; control data channel — WRTC-01, WRTC-02, WRTC-04.
4. Settings and `/healthz` — WRTC-03.
5. Playground: Test call uses WebRTC when chosen in Technical details (optional) — covered by WRTC-01 by hand.
6. Tests citing the IDs (offer/answer and token checks without network; media by hand).

# Risks and rollout

* A TURN service is a new paid dependency and processes call audio: it needs the same BAA coverage as other processors in production.
* Media through TURN adds latency; measured in S6.

# Out of scope

Video; SFU rooms with several participants; the browser SDK beyond the playground.
