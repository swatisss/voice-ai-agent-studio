---
type: Decision Record
title: ADR-0002 Voice pipeline
description: Use Pipecat for transport, VAD, STT and TTS over a plain WebSocket, with our own turn aggregator and a brain processor wrapping the shared agent runtime.
status: stable
tags: [decision, voice, pipecat]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Context

v1 tests voice from the browser only; telephony (SIP/IVR) comes later. The voice path must run identically on localhost and Cloud Run, stay cheap, and share one "brain" with text chat and simulated evaluation calls.

# Options

1. **LiveKit Agents + LiveKit Cloud** — robust WebRTC and SIP, but adds a media service, tokens and dispatch to set up and debug.
2. **Pipecat with SmallWebRTC** — good audio, but WebRTC needs UDP, which Cloud Run does not support without a TURN server.
3. **Pipecat with a plain WebSocket** — runs anywhere HTTP runs (localhost, Cloud Run); slightly more latency than WebRTC; the same pattern later maps to telephony media streams (Twilio sends audio over WebSockets).

# Decision

Option 3. Pipecat provides the transport, Silero VAD, Deepgram STT/TTS and interruption handling. We do **not** use Pipecat's LLM services or context aggregators: our `TurnAggregator` and `BrainProcessor` hand each caller turn to the shared `AgentSession` ([/architecture/agent-runtime.md](/architecture/agent-runtime.md)). Wire format is raw PCM with tiny JSON control messages ([/api/voice-protocol.md](/api/voice-protocol.md)) and a hand-written browser client.

# Consequences

* One brain for voice, text and simulation — evaluation results reflect real call behavior.
* Pipecat usage is confined to `voiceai/voice/`, limiting the blast radius of its frequent API changes; a smoke test guards construction.
* Echo cancellation relies on the browser; a headset is recommended for demos.
* Telephony later: swap the serializer for a Twilio/Telnyx media-stream serializer; the rest of the pipeline stays.
