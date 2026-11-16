---
type: Decision Record
title: ADR-0015 A hosted media room (LiveKit Cloud) for live voice handover
description: Customer, AI, specialist and a transcribing scribe meet in a LiveKit Cloud room so a human can take a voice call from another machine; the AI runs in our service through Pipecat's LiveKit transport; a WebSocket relay and Daily were considered.
status: draft
tags: [decision, voice, livekit, handover, deployment]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Context

The owner wants a live voice handover: a customer talks to the AI in the browser; on escalation a specialist on another machine takes the voice call; both legs are transcribed so the specialist's words teach the agent. Today an escalation ends the AI call (CE-01), Agent Desk has no audio, and the WebRTC transport ([/architecture/webrtc-transport.md](/architecture/webrtc-transport.md)) is one customer and one pipeline, needing a TURN relay because Cloud Run takes no inbound UDP. [ADR-0013](adr-0013-carrier-adapters-and-sip-paths.md) rejected running a SIP/media server ourselves; a hosted service is a different question.

Research (2026-11-16, primary sources; `.scratch/human-voice-and-channels/research/02-livekit-cloud.md` has the URLs):

* LiveKit Cloud Build plan: $0, no credit card, 5,000 WebRTC participant-minutes, 100 concurrent connections, 60 egress minutes; allowances are hard caps.
* A browser joins with a backend-minted JWT and `livekit-client`; Pipecat's `LiveKitTransport` joins a room as a participant from any Python process and delivers each participant's audio tagged by identity; LiveKit Agents needs a separate "agent server" process.
* OpenAI Realtime plugs into both; Pipecat's docs do not address it with a multi-participant transport (UNVERIFIED).
* Cloud Run takes outbound connections and WebSockets; its docs never mention outbound UDP, so media from Cloud Run is UNVERIFIED.
* LiveKit's warm-transfer task is SIP-based; a browser specialist uses plain room membership instead.

# Options

1. **WebSocket audio relay of our own.** Reuses the voice WebSocket; no vendor. We would build the mixer, jitter handling, echo behaviour and three-way routing in the specialist's browser and the API. Media stays on Cloud Run, which is fine over TCP but is exactly the part vendors sell.
2. **LiveKit Cloud room, AI via Pipecat inside our service.** Hosted media, free to try, token + SDK on the browser, our existing STT/LLM/TTS and turn policy unchanged, later SIP for phone phases. Adds a vendor and a media-path unknown on Cloud Run.
3. **LiveKit Cloud room, AI as a LiveKit Agents worker.** Cleanest LiveKit story (dispatch, built-in transcription) but a second runtime that re-implements our session model, scoring and tools, or a second deployed service.
4. **Daily** (`DailyTransport`). Equivalent shape, built-in recording and transcription, 10,000 free minutes a month on the Video SDK page; card requirement and recording price not stated on the page read. A viable swap; nothing here is LiveKit-specific except the token and client SDK.

# Decision

Option 2. A voice call may use `transport: livekit`: the room is `lk-<call_id>`, the AI is a Pipecat `LiveKitTransport` participant in the API process (outbound only), the customer and the specialist are browser participants with least-privilege tokens, and a subscribe-only scribe transcribes each human track with our STT. On escalation the call stays open; when the specialist connects the AI introduces them and leaves. Details, flow and acceptance: [/architecture/hosted-media-room.md](/architecture/hosted-media-room.md).

**Gate and fallback.** The first task of CP-0050 is a connectivity check (`scripts/livekit_check.py`) from the Cloud Run service. If media does not leave Cloud Run over UDP, TCP/TURN is accepted if the round trip stays under the demo bar; if nothing works, the AI participant moves to a separate always-on worker (a small VM or container host) behind the same interfaces, or the owner picks option 1 or 4. The specs do not change in that case beyond [deployment](/architecture/deployment.md).

# Consequences

* New environment: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (secrets in Secret Manager on Cloud Run), `LIVEKIT_TOKEN_TTL_S`, `HANDOVER_WAIT_S`. Without them everything else works; the transport answers 503.
* New dependencies: `pipecat-ai[livekit]` (inside `voiceai/voice/`, as for all Pipecat), `livekit-api` for tokens and room administration; web `livekit-client`.
* Call ending changes for room calls: an escalation does not end the call (CE-01 is scoped to other transports); new end reasons `human_ended` and `handover_timeout`.
* Cost: participant-minutes per staffed call up to four; the free plan stops hard at its caps (calls fail, no bill). Paid Ship is $50/month plus $0.0005 per participant-minute.
* Healthcare: HIPAA material is on LiveKit's Scale plan; this repo is synthetic-data only. A BAA is an owner decision before real members.
* Audio is not recorded; recording needs a bucket the owner owns and is a later CP.
* Phone calls (Phase 2 of the research) can later reuse the room with LiveKit SIP; nothing here blocks it.
