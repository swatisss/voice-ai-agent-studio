---
type: Change Proposal
title: CP-0012 Phone channel (Twilio) and optional realtime speech-to-speech voice
description: "Let callers reach published agents by phone through Twilio Media Streams, add an optional OpenAI Realtime speech-to-speech pipeline per agent, and seed a new Insurance Claims Agent that uses it."
status: stable
cp_state: implemented
tags: [telephony, voice, realtime, twilio, openai, claims]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Why

Today an agent can only be tested from the browser (Test call). Agents are meant to sit behind an IVR or a phone number, and nothing in the platform can answer a real telephone call; [/product/scope.md](/product/scope.md) lists telephony as out of scope and [ADR-0002](/decisions/adr-0002-voice-pipeline.md) already planned for it ("swap the serializer for a Twilio media-stream serializer").

Separately, the voice pipeline is a cascade (speech-to-text, then the text brain, then text-to-speech). Each hop adds latency before the caller hears anything. OpenAI's Realtime API is a single speech-to-speech model that listens and talks over one streaming connection, usually with a shorter gap between the caller finishing and the agent answering. The team wants to try it on one agent without touching the others.

The deployment target is GCP (Cloud Run, already specified), which supports WebSockets but not UDP, so Twilio Media Streams (audio over WSS) is the telephony route that fits with the least new infrastructure. The developer must also be able to verify the whole phone path on a laptop before deploying anything.

# What changes

1. **Phone channel.** A Twilio number points its voice webhook at the platform. The webhook looks up which published agent owns the dialled number, creates a voice call and answers with TwiML that connects the call's audio to a WebSocket on the platform. The same pipeline as the browser runs on that socket (8 kHz mu-law in and out). Barge-in, welcome, silence and maximum-length timers, escalation and feedback-less call ending all behave as in browser voice calls. Details: [/architecture/telephony.md](/architecture/telephony.md).
2. **IVR in front.** An IVR (or any caller) reaches the agent by forwarding to the Twilio number or its SIP URI. Context the IVR passes (`ivr_*` parameters) is copied into the call context and shown to the agent, and never counts as identity verification.
3. **Hand-off to a person on the phone.** When a phone call is escalated, the agent speaks the hand-off message and, if the agent has a `telephony.transfer_to` number, the platform asks Twilio to redirect the live call there. Without one, the call ends as today and the escalation waits in the console.
4. **Optional realtime pipeline.** A new agent setting `voice.pipeline` (`cascade` default, or `realtime`). A realtime agent's voice calls, on the browser and on the phone, run through the OpenAI Realtime speech-to-speech service. The system prompt, tools, skills, knowledge, verification gate, escalation, call state, events and fleet learning are the **same shared runtime** as in the cascade; only the audio-in to audio-out part is replaced. Details and trade-offs: [/architecture/realtime-voice.md](/architecture/realtime-voice.md). Every existing agent stays on `cascade`; the Deepgram pipeline is not modified.
5. **New agent: Insurance Claims Agent** (Evergreen Health, inbound, realtime pipeline). It reports claim status, takes a first notice of a new claim, explains required documents and escalates disputes. It brings two new mock-API tools, a three-article knowledge base, a persona, skills, regression scenarios and an eighth use case. Details: [/demo-data/claims-agent.md](/demo-data/claims-agent.md).
6. **Run it locally first.** A new runbook ([/build/runbook-phone.md](/build/runbook-phone.md)) covers a Twilio trial number, an ngrok or cloudflared tunnel, `PUBLIC_BASE_URL`, the number-to-agent mapping and a test call from a real phone; plus `scripts/fake_twilio.py`, which replays a Twilio call from a WAV file so the path can be checked with no Twilio account at all.
7. **Deploy on GCP.** Cloud Run settings already fit (3600 s timeout, one instance, CPU always on, session affinity). Added: `PUBLIC_BASE_URL`, optional secrets `TWILIO_AUTH_TOKEN` and `TWILIO_ACCOUNT_SID`, `OPENAI_API_KEY` needed for realtime agents, and `/healthz` reports `providers.twilio`.

# Affected specs

New:

* [/architecture/telephony.md](/architecture/telephony.md) - Twilio webhook and media stream, number mapping, IVR context, transfer, security, acceptance TEL-01…TEL-11.
* [/architecture/realtime-voice.md](/architecture/realtime-voice.md) - the optional speech-to-speech pipeline, streaming and latency, how shared runtime pieces are reused, evaluation trade-offs, RV-01…RV-14.
* [/decisions/adr-0008-telephony-and-realtime-voice.md](/decisions/adr-0008-telephony-and-realtime-voice.md) - why Twilio Media Streams, why OpenAI Realtime as an optional mode.
* [/build/runbook-phone.md](/build/runbook-phone.md) - local and Cloud Run phone setup and test runbook.
* [/demo-data/claims-agent.md](/demo-data/claims-agent.md) and [/demo-data/kb/claims/](/demo-data/kb/claims/) - the Insurance Claims Agent, CLM-01…CLM-03.
* [/prompts/realtime-addendum.md](/prompts/realtime-addendum.md) - extra instructions appended to the system prompt in realtime mode.

Changed:

* [/product/scope.md](/product/scope.md) - inbound phone calls move into scope; IVR/CCaaS connectors, SIP trunks, outbound dialing stay out.
* [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) - pipeline selection and transport profiles; cascade behavior unchanged.
* [/api/voice-protocol.md](/api/voice-protocol.md) - pipeline-independent; pointer to the Twilio stream.
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - the two methods an externally driven (speech-to-speech) channel uses, RT-10.
* [/architecture/escalation.md](/architecture/escalation.md), [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md) - phone transfer on hand-off.
* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) - a `speech` role for the realtime model, audio prices, LG-12, LG-13.
* [/architecture/evaluation.md](/architecture/evaluation.md) - simulation of a realtime agent runs on the text brain.
* [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) - telephony routes resolve the tenant from the dialled number.
* [/architecture/deployment.md](/architecture/deployment.md), [/build/runbook-gcp.md](/build/runbook-gcp.md), [/build/runbook-local.md](/build/runbook-local.md) - environment, secrets, health, DEP-04.
* [/architecture/tech-stack.md](/architecture/tech-stack.md), [/decisions/adr-0002-voice-pipeline.md](/decisions/adr-0002-voice-pipeline.md) - providers and the telephony pointer.
* [/data/data-model.md](/data/data-model.md) - table `phone_numbers`, `calls.meta.telephony`, 21 tables (DM-01).
* [/data/agent-config.md](/data/agent-config.md) - `voice.pipeline`, `voice.realtime`, `telephony.transfer_to`, `models.speech`.
* [/api/rest-api.md](/api/rest-api.md) - phone-number endpoints and the telephony routes.
* [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md) - claim first notice and required documents, MOCK-13, MOCK-14.
* [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md), [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md), [/product/use-cases.md](/product/use-cases.md), [/product/vision.md](/product/vision.md) - fifth agent, 18 tools, eighth use case (UC-01, UC-02 reworded).
* [/ui/agent-builder.md](/ui/agent-builder.md) - voice pipeline choice and transfer number, UI-38; [/ui/calls.md](/ui/calls.md) - phone badge, UI-39.
* [/process/conventions.md](/process/conventions.md) - new acceptance prefixes `TEL`, `RV`, `CLM`.

# Acceptance criteria

New, defined in the specs above: TEL-01…TEL-11 ([/architecture/telephony.md](/architecture/telephony.md)), RV-01…RV-14 ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)), CLM-01…CLM-03 ([/demo-data/claims-agent.md](/demo-data/claims-agent.md)), MOCK-13, MOCK-14, LG-12, LG-13, RT-10, DEP-04, UI-38, UI-39.
Reworded: DM-01 (21 tables), UC-01 (five agents, 18 tools), UC-02 (eight use cases).

# Tasks

1. Spec edits and this proposal (done in this CP).
2. **Spike S4 first** ([/verification/spikes.md](/verification/spikes.md) gets a new entry when done): with the Pipecat version pinned in `pyproject.toml`, confirm (a) the OpenAI Realtime service class, its function-calling and transcript events, (b) `TwilioFrameSerializer` with a FastAPI WebSocket, (c) that Twilio signs or accepts the stream handshake as assumed in TEL-04, (d) how an IVR's SIP headers or parameters reach the webhook (TEL-05), (e) the realtime model id, voices and prices from the OpenAI console, (f) measured end-of-speech to first-audio latency for browser and phone. Record versions and findings; adjust the specs before coding if any assumption fails.
3. Data and config: `phone_numbers` table, config schema fields, validation, `voiceai phone add|list|remove` CLI — covers DM-01, TEL-08, RV-01, UI-38 (API side).
4. Gateway: `speech` role, model entry with audio prices, `GET /api/models` filtering — covers LG-12, LG-13.
5. Runtime: `AgentSession.run_tool` and transcript recording used by the realtime bridge — covers RT-10, RV-05, RV-06.
6. Voice: pipeline selection, transport profiles (browser, Twilio), realtime pipeline with `RealtimeBridge`, timers, welcome, hand-off speech — covers RV-02…RV-14.
7. Telephony: webhook route, signature validation, TwiML, stream token, stream WebSocket, IVR parameters, transfer via Twilio REST — covers TEL-01…TEL-07, TEL-10, TEL-11.
8. Mock API and seed: two tools, claims KB, persona, skills, scenarios, eighth use case — covers MOCK-13, MOCK-14, CLM-01…CLM-03, UC-01, UC-02.
9. Web: Voice tab pipeline select and transfer number; phone badge on Calls — covers UI-38, UI-39.
10. Tooling and docs: `scripts/fake_twilio.py` (TEL-09), `apps/api/.env.example`, README, deploy script (`PUBLIC_BASE_URL`, optional Twilio secrets), runbooks — covers DEP-04, TEL-09.
11. Tests citing the IDs above (no network: stubbed OpenAI Realtime service, stubbed Twilio REST, signature fixtures); manual checks recorded in `scripts/acceptance-baseline.txt` with reasons (real phone call, real Realtime audio, Cloud Run).

# Risks and rollout

* **Pipecat API drift.** The Realtime and Twilio classes change between releases; usage stays inside `voiceai/voice/` and is guarded by a smoke test like VO-06. Spike S4 comes before code.
* **Trade-off of speech-to-speech.** The model decides what to say, so the platform's deterministic wording (farewell line, safety message, hand-off message, silence reminders) is enforced by cancelling the model's response and speaking exact text, which can leave a half-second of the model's own speech audible. Prompts, tools and verification are still ours, but the model's tone and wording vary more than with the text brain. Realtime audio costs more per minute than the cascade. See [/architecture/realtime-voice.md](/architecture/realtime-voice.md).
* **Evaluation fidelity.** Simulated evaluation calls use the text brain, so a realtime agent's scores approximate, and do not prove, its spoken behavior. The Insights page should keep showing real call outcomes; this is stated in the evaluation spec.
* **Single instance.** [ADR-0005](/decisions/adr-0005-single-service.md) keeps one Cloud Run instance; concurrent phone calls share its CPU. The spike measures how many concurrent calls one 2 vCPU instance holds for each pipeline, and the figure goes into the deployment spec.
* **Security.** The Twilio webhook is public. It rejects unsigned requests (TEL-02) and the stream accepts only a short-lived, call-bound token (TEL-04). Signature validation cannot be disabled on Cloud Run (TEL-10).
* **Privacy.** Phone audio passes through Twilio and OpenAI. Only synthetic data may be used until compliant agreements exist ([/product/healthcare-compliance.md](/product/healthcare-compliance.md)). The caller's number is stored as last four digits only.
* **Trial accounts.** A Twilio trial plays a short notice before connecting and can only call verified numbers; the runbook says so.
* **Tunnel URLs.** ngrok and cloudflared quick-tunnel URLs change on restart; `PUBLIC_BASE_URL` and the Twilio webhook must both be updated, or signature validation fails (the runbook's first troubleshooting entry).
* **Rollback.** Remove the number mapping to stop phone traffic; set `voice.pipeline` back to `cascade` and publish to stop using the Realtime API. No existing agent or data is migrated. The new table is created at startup.

# Implementation notes (2026-10-16)

Accepted as proposed; the answers to the questions below were: the realtime model is the OpenAI Realtime API from Cloud Run, a PSTN number or SIP URI per agent, the claims agent files a mock claim, OpenAI voices for realtime agents. What changed while implementing, all recorded in the specs:

* **Own bridge instead of Pipecat's Realtime service** (spike S4, [/verification/spikes.md](/verification/spikes.md)): Pipecat 1.12's service is driven by its LLM context aggregators and cannot take exact-text responses or hand tool calls to `AgentSession`. `voiceai/voice/realtime.py` speaks the provider's WebSocket protocol; Pipecat still provides transports, serializers and frames. The model ID is therefore Pipecat's default (`gpt-realtime-2.1`) and prices stay placeholders until confirmed in the OpenAI console.
* **Spec amendments found by the code:** the inbound mode prompt now renders `call_context` so IVR context reaches the model ([/prompts/mode-inbound.md](/prompts/mode-inbound.md), a prompt change for every inbound agent: one extra line, `(no context)` when empty); RV-15 (live PATCH on a realtime call is a 409); `settings.pipeline` in call responses; `OPENAI_REALTIME_URL`; `telephony` in the call detail.
* **Two existing tests were updated** for the specified changes (21 tables, the `/healthz` provider list) and two for the new agent (five agents, 18 tools, the Claims agent's four scenarios).

Not verified here (no OpenAI or Twilio credentials in this session; see S4): a call from a real phone, the real Realtime service, measured latency and concurrency, Cloud Run. The phone path was exercised end to end against a scripted Realtime server instead.

# Open questions for the reviewer

1. **"On GCP" for speech-to-speech.** This CP treats the realtime model as the OpenAI Realtime API called from Cloud Run (the team has an OpenAI key, [CP-0008](/changes/cp-0008-openai-provider.md)). Google's Gemini Live API on Vertex AI is the GCP-native alternative and would keep audio inside GCP; it is not included. Say if you want it instead, or as a second realtime provider later.
2. **Transfer target.** Is a PSTN number or SIP URI per agent (`telephony.transfer_to`) enough for v1, or should the number depend on the escalation category?
3. **Claims agent scope.** First notice of a new claim is a mock write (it creates a claim in the in-memory mock data, reset on `seed --reset`). Is that the right depth, or should the agent only report status and requirements?
4. **Persona voice in realtime mode.** Deepgram Aura voices cannot be used by the Realtime model; realtime agents choose an OpenAI voice in `voice.realtime.voice` and the persona's voice is ignored. Acceptable?
5. **Recording.** Not included (audio recording is out of scope); Twilio call recording stays off.

# Out of scope

* Outbound dialing through Twilio (outbound agents stay simulated in the browser), SMS, voicemail detection.
* SIP trunking, RTP, and IVR/CCaaS connectors other than "forward the call to the Twilio number or SIP URI" (Genesys, Amazon Connect).
* Warm transfer with live audio hand-over or a conference leg; the transfer here is a redirect of the call.
* Other carriers (Telnyx, Vonage) and other realtime providers (Gemini Live, Nova Sonic); the transport profile and bridge are shaped so they can be added by a later CP.
* A phone-number management page in the web app (API and CLI only), call recording, DTMF input, multiple languages.
* Changing any existing agent to the realtime pipeline.
