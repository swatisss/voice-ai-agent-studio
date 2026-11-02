---
type: Decision Record
title: ADR-0013 Carrier adapters and the paths to SIP
description: Phone carriers plug in behind one carrier-adapter interface (Twilio is the only adapter for now), and SIP reaches the platform through a carrier's SIP trunk, the customer's own Asterisk over WebSocket, or a speech model's own SIP endpoint - never as raw RTP on Cloud Run.
status: draft
tags: [decision, telephony, sip, twilio, asterisk]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-02T00:00:00Z" }
---

# Context

[ADR-0008](adr-0008-telephony-and-realtime-voice.md) chose Twilio Media Streams because Cloud Run takes HTTP, WebSocket and gRPC but no UDP, so SIP signalling and RTP audio cannot end on our service. Health plans and insurers often run their own phone systems and ask for SIP. The product owner (2026-11-02) wants the platform built so any SIP source can be added, keeping Twilio as the only carrier for now.

How others do it (checked 2026-11-02):

* **Dograh** (open source, BSD-2) never terminates SIP or RTP itself. Each carrier is a self-registering package (`ProviderSpec`) with its webhook routes, credential schema and a serializer; audio always arrives over a WebSocket through Pipecat's `FastAPIWebsocketTransport` (Twilio and Plivo 8 kHz mu-law JSON frames, Vonage 16 kHz PCM binary frames, Telnyx call control). SIP comes through a SIP-capable carrier (Cloudonix) or **Asterisk ARI**, where Asterisk terminates SIP and RTP and streams the audio to Dograh over a WebSocket with `externalMedia`. https://docs.dograh.com/integrations/telephony/custom · https://github.com/dograh-hq/dograh/tree/main/api/services/telephony
* **Asterisk** ships a WebSocket channel driver (`chan_websocket`, usable from ARI `externalMedia` with `transport=websocket`) since 23.0.0, 22.6.0, 21.11.0 and 20.16.0: binary frames carry media, text frames carry control. https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket
* **Speech-to-speech providers** with their own SIP endpoints (OpenAI, xAI, ElevenLabs) take a SIP trunk directly and give our server webhooks plus a control WebSocket, so no audio touches us (`.scratch/speech-to-speech-voice/research/02-direct-sip.md`).
* Our Pipecat install already ships serializers for Twilio, Telnyx, Plivo, Vonage, Exotel and Genesys.

# Options

1. **Carrier media streams** - each carrier (Twilio, Telnyx, Plivo, Vonage, Exotel) sends audio over a WebSocket; one adapter per carrier.
2. **SIP through a carrier's trunk** - the customer's PBX or IVR sends SIP to the carrier (Twilio Elastic SIP Trunking or a SIP domain), and the carrier streams to us as in 1. Works today with Twilio (IVR forwards to a Twilio SIP URI, `X-IVR-*` headers become call context).
3. **The customer's own Asterisk (or FreeSWITCH) over WebSocket** - Asterisk inside the customer's network terminates SIP and RTP, and `externalMedia` streams the call to us over a WebSocket. Audio never crosses a third-party carrier, which suits regulated customers; one adapter.
4. **A speech model's own SIP endpoint** - the trunk goes straight to the realtime model; we keep tools, transcripts, hang-up and transfer through webhooks and a control socket. Only for the realtime pipeline.
5. **Run a SIP/RTP bridge ourselves** (LiveKit SIP, FreeSWITCH on a VM or GKE) - needs UDP, a second runtime and its security; against [ADR-0005](adr-0005-single-service.md).

# Decision

* All carrier-specific code sits behind one **carrier adapter** interface ([/architecture/telephony.md](/architecture/telephony.md), Carrier adapters): verify the webhook, read the inbound call, answer with a stream, refuse, build the audio serializer, transfer, report whether it is configured. Routes are `/api/telephony/{carrier}/…`; Twilio is the only registered adapter and its URLs do not change.
* SIP is supported through **option 2 now** (Twilio SIP trunk or SIP domain into the Twilio adapter), with **option 3** (an `asterisk` adapter) as the next adapter for customers who run their own phone system, and **option 4** for realtime agents when a CP asks for it. Option 5 is not chosen.
* Adding a carrier means one adapter module and its registration; the pipeline, brain, verification, escalation and scoring do not change.

# Consequences

* Behaviour of phone calls is unchanged (TEL-01…TEL-12); TEL-13 covers the adapter registry.
* The pitch can show "any carrier or SIP source plugs in" with the interface in code and the three SIP paths written down, without a second carrier contract.
* Every new adapter still needs its own CP: its webhook security, its audio format, how it passes IVR context and how it transfers.
