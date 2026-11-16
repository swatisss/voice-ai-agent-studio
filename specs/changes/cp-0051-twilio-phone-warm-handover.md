---
type: Change Proposal
title: CP-0051 Twilio phone warm handover with a recorded, transcribed human leg
description: An escalated phone call becomes a Twilio conference - the specialist's Indian phone or browser is rung and briefed, bridged warm, recorded on two channels - and a batch transcription writes the human portion into the call's events so the learning loop learns from what the person said.
status: draft
cp_state: accepted
tags: [telephony, twilio, escalation, handover, india, learning]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The owner (Phase 3, "everything on Twilio") wants to dial a Twilio US number from an Indian mobile, have the AI answer, and on escalation have the call taken by a person at another Indian number or in the specialist's browser. Today the escalated call is a cold `<Dial>` (TEL-07): no briefing, no recording, and the platform never learns what the person told the caller, so the self-learning loop sees only the resolution note. Research (`.scratch/human-voice-and-channels/research/03-twilio-handover-whatsapp.md`, 2026-11-16) re-verified from Twilio's docs that a conference-based warm handover, dual-channel recording callbacks and the Voice SDK are available on the existing account type, with a short list of points to confirm on a paid account (spikes S1 to S5, S9).

# What changes

* **Handover modes.** `telephony.handover.mode`: `dial` (default, today's behaviour; optional two-channel recording) or `conference` (new). Also `record`, `ring_seconds`, `browser`, `brief`.
* **Conference handover.** The caller is moved into a Twilio conference and waits; the specialist's phone (and, optionally, Ready specialists' browsers) is rung with a spoken, masked brief from the groundwork packet; the first to answer is bridged; a browser answer accepts the escalation. No answer gives the caller a call-back apology and a hang-up; nothing is retried.
* **Recording and transcription.** With `record: true` the caller hears a notice, the conference is recorded, Twilio's recording callback creates a `call_recordings` row and a `transcribe_handover` job downloads the two-channel audio, transcribes each channel through a new small `Transcriber` interface (Deepgram pre-recorded by default; Sarvam is an option behind it after an ADR) and appends `user` and `human` events with `on_human_leg: true`. Audio is not stored; the Twilio recording is deleted afterwards.
* **Learning loop.** The call is re-analysed with the human portion, the fix drafter's evidence gains "Human portion (specialist): …", and the scorecard keeps judging only the AI.
* **Agent Desk.** A "Take calls in this browser" control (Twilio Voice SDK) with presence, an incoming-handover banner with the masked packet, a call bar, and the "Specialist call" section in call detail.
* **Runbook and demo.** Owner steps in the Twilio console, the spikes, and a demo script ([/build/runbook-twilio-handover-whatsapp.md](/build/runbook-twilio-handover-whatsapp.md)).

# Affected specs

* [/architecture/phone-warm-handover.md](/architecture/phone-warm-handover.md) - new (TEL-14 to TEL-27)
* [/architecture/telephony.md](/architecture/telephony.md) - Transfer to a person (modes), adapter `transfer(call_ref, plan)`, settings, TEL-07 scoped to `dial` mode
* [/architecture/escalation.md](/architecture/escalation.md) - step 6 and ES-14
* [/architecture/agent-desk.md](/architecture/agent-desk.md) - allow-list (phone token, presence, channel replies), DESK-12
* [/ui/agent-desk.md](/ui/agent-desk.md) - phone control, banner, call bar, specialist call section, WhatsApp panel additions (UI-91 to UI-95)
* [/data/data-model.md](/data/data-model.md) - `call_recordings`, `desk_presence` (DM-21); [/data/agent-config.md](/data/agent-config.md) - `telephony.handover`
* [/api/rest-api.md](/api/rest-api.md) - desk phone endpoints, call `handover` and `recordings` (API-21 to API-23); [/api/events.md](/api/events.md) - `handover.transcribed`
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) - `transcribe_handover`; [/architecture/fleet-learning.md](/architecture/fleet-learning.md) - human portion as evidence
* [/build/runbook-twilio-handover-whatsapp.md](/build/runbook-twilio-handover-whatsapp.md) - new

# Acceptance criteria

New: TEL-14 to TEL-27, DESK-12, ES-14 (shared with CP-0052), UI-91 to UI-93, DM-21, API-21 to API-23. Changed: TEL-07 (applies to `dial` mode). No existing ID is reused.

# Dependencies

* **CP-0049** (human message channel): the `human` event kind (DM-17) must exist; if CP-0049 is not merged first, this CP adds the kind itself.
* UI and DM numbers (UI-91 to UI-95, DM-20/21, API-20 to API-23) are chosen above CP-0049's and CP-0050's blocks; renumber at merge if another change took them.

# ADR note (Hindi and Indic transcription of the human leg)

* The human leg is Hindi, English or a mix. The repo has streaming Deepgram STT in the cascade but no batch transcription interface, so the CP adds `Transcriber` (mono WAV and language hints in, timed segments out) with **Deepgram pre-recorded** as the default (key already required; per-channel requests). Deepgram's Hindi coverage for code-mixed speech is not confirmed from its pages.
* **Sarvam** (Indian languages, code-mixed mode on `saaras:v3`, short-audio REST with a batch API for longer files and diarization at separate pricing) is the likely better fit for Hinglish. **No vendor is added by this CP**: adopting it needs an ADR (data leaves to a new third party, residency and DPA, key handling, cost, 8 kHz behaviour undocumented) and a measured comparison on a scripted bilingual specialist call. Until then `HANDOVER_STT_PROVIDER=deepgram`.

# Tasks

1. Spec edits (done in this CP).
2. **Spikes S1 to S5, S9** on the owner's paid account (runbook section C); record findings here; adjust the spec where Twilio behaves differently (for example `<Connect action>` instead of a REST update, a `<Dial><Client>` route, mono recordings).
3. Backend: `telephony.handover` validation (TEL-14); adapter `transfer(call_ref, plan)` with `dial` unchanged (TEL-07, TEL-16) and `conference` (TEL-15, TEL-17, TEL-18, TEL-19, TEL-26); signed callback routes (TEL-20); `call_recordings` and the job (TEL-21 to TEL-23); learning hooks (TEL-24); phone token and presence (TEL-25, DESK-12); `/healthz` flag; settings; `fake_twilio.py --handover` (simulates the callbacks, no network).
4. `Transcriber` interface with the Deepgram implementation and a fake for tests.
5. Web: phone control, banner, call bar, specialist call section (UI-91 to UI-93).
6. Tests (fake Twilio client, fake Transcriber, temp SQLite, no network) citing the IDs; baseline lines only for UI IDs awaiting a click-through and TEL-27 (by hand).

# Risks and rollout

* **Twilio specifics unconfirmed** (listed in the research note and the runbook): inbound from India to a US number, behaviour of the open stream on a REST update, `client:` as a `Calls.create` destination, the conference dual-channel setting (two Twilio pages disagree), callback field names. Each has a fallback in the spec; none is claimed as verified.
* **Cost and consent.** Indian legs cost about $0.05 a minute; recording consent and Indian call rules are the owner's decision; `record` defaults to off and the caller hears a notice when it is on.
* **Latency of the handover** (the specialist's phone ringing time) is measured, not assumed.
* Default behaviour is unchanged: an agent without `handover` keeps the cold transfer.
* DM-01's table count changes with this CP and the other accepted ones.

# Out of scope

* The AI staying in the conference to introduce the parties; live captions of the human leg; returning the caller to the AI after the human; outbound AI calls; an Indian carrier or Indian number (a later adapter CP); Sarvam (needs an ADR); LiveKit (CP-0050); routing among several specialists by skill or availability beyond Ready presence.
