---
type: Decision Record
title: ADR-0008 Telephony through Twilio Media Streams and an optional realtime voice pipeline
description: Answer phone calls with Twilio Media Streams over a WebSocket on Cloud Run, and offer OpenAI Realtime speech-to-speech as a per-agent option beside the Deepgram cascade.
status: draft
tags: [decision, telephony, voice, twilio, openai]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Context

Agents are meant to answer a phone and sit behind an IVR, but v1 only has the browser Test call ([/product/scope.md](/product/scope.md)). [ADR-0002](adr-0002-voice-pipeline.md) chose a plain WebSocket because it runs the same on a laptop and on Cloud Run, and noted that telephony would swap the serializer. Cloud Run accepts HTTP, WebSocket and gRPC but no UDP, so raw SIP/RTP cannot terminate there. The deployment target is GCP and the developer must verify phone calls locally before deploying.

Latency is the second driver. The cascade (speech-to-text, text brain, text-to-speech) is cheap and fully controllable but every hop adds delay. OpenAI offers a speech-to-speech Realtime API; the team holds an OpenAI key ([ADR-0007](adr-0007-openai-provider.md)).

# Options

Telephony:

1. **Twilio Media Streams** - Twilio terminates the phone call and streams audio over a WebSocket to us. Works on Cloud Run, works on a laptop through a tunnel, Pipecat ships a serializer for it.
2. **SIP trunk plus a media bridge** (LiveKit SIP, Asterisk, FreeSWITCH) - needs UDP/RTP and a VM or GKE; more to run and secure.
3. **CCaaS connectors** (Genesys AudioHook, Amazon Connect) - one adapter per vendor; later, on demand.

Voice pipeline:

A. **Cascade only** - unchanged; no latency improvement.
B. **Replace the cascade with a realtime model** - lower latency, but loses the shared, testable brain, deterministic wording and cheap per-minute cost for every agent.
C. **Both, chosen per agent** - realtime where it pays off, cascade elsewhere.
D. **Gemini Live on Vertex AI** instead of OpenAI - GCP-native, keeps audio inside GCP; not chosen now because the team has an OpenAI key and the Realtime service is already in Pipecat. The bridge is written so a second provider can be added later.

# Decision

Telephony: option 1, inbound only, with the IVR forwarding to a Twilio number or SIP URI. Voice pipeline: option C. `voice.pipeline` defaults to `cascade`; `realtime` is chosen per agent and the first realtime agent is the Insurance Claims Agent. In realtime mode the speech model replaces only audio-in to audio-out; the system prompt, tools, verification gate, escalation, state, events and fleet learning stay in the shared `AgentSession` ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)). Fixed lines (welcome, farewell, safety, hand-off) are spoken as exact text by cancelling the model's response and having the service read the text.

# Consequences

* Phone and browser calls run the same pipelines; only the serializer and a thin route differ ([/architecture/telephony.md](/architecture/telephony.md)).
* Cloud Run needs no new infrastructure: a public HTTPS service, a longer WebSocket timeout (already 3600 s), and a few secrets. Concurrency is bounded by the single instance ([ADR-0005](adr-0005-single-service.md)); the spike measures it.
* The webhook is public and therefore signature-checked; the stream is protected by a call-bound token.
* Realtime calls cost more per minute and vary more in wording than cascade calls. Simulated evaluation cannot exercise the speech model, so it is labelled a text approximation.
* A tunnel (ngrok or cloudflared) is needed for local phone tests, or `scripts/fake_twilio.py` for a no-account check.
* Audio passes through two more third parties (Twilio, OpenAI); synthetic data only ([/product/healthcare-compliance.md](/product/healthcare-compliance.md)).
* Outbound dialing, SIP and CCaaS connectors, warm transfer and other realtime providers each need their own CP.
