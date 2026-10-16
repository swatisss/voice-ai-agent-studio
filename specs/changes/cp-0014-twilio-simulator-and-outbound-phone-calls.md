---
type: Change Proposal
title: CP-0014 Twilio simulator and outbound phone calls
description: A local Twilio simulator with a browser phone, so the whole phone path runs with no Twilio account; real outbound calls through Twilio's API (or the simulator); a Claims Follow-up Agent as the outbound use case.
status: stable
cp_state: implemented
tags: [telephony, simulator, outbound, demo]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Why

A Twilio account (and, for most people, its paid number) is not always available, yet the demo must show a phone conversation, and it must show an **outbound** call: the agent phones the customer. Today outbound agents are only simulated in the browser, and the phone path needs real Twilio. The team wants to demo now with a simulator and later switch to real Twilio by changing credentials only.

# What changes

1. **Twilio simulator** (`scripts/twilio_sim.py`, [/build/twilio-simulator.md](/build/twilio-simulator.md)). One local server that behaves like Twilio towards the platform: it answers the REST calls the platform makes (`IncomingPhoneNumbers`, `Calls` create and update) and, when a call is dialled or an outbound call is answered, it drives the platform exactly as Twilio would (signed webhook, TwiML, Media Stream events with mu-law audio). Its web page is a **browser phone**: a dial pad for inbound calls, an "incoming call" banner with Answer and Decline for outbound ones, and your microphone and speaker as the handset. The platform cannot tell it from Twilio; moving to real Twilio means pointing the same settings at Twilio.
2. **Outbound phone calls** ([/architecture/telephony.md](/architecture/telephony.md)). `POST /api/phone/outbound` places a call from an outbound agent to a phone number through Twilio's REST API (real Twilio or the simulator): the agent speaks the persona opening when the call is answered, unanswered calls are closed after a ring timeout.
3. **Outbound use case: Claims Follow-up** ([/demo-data/claims-agent.md](/demo-data/claims-agent.md)). A new outbound agent on the realtime pipeline that calls members whose claim is waiting on something (a missing document) or still processing, explains where it stands and what is needed. Targets come from a new mock list.
4. **Demo launcher** `scripts/phone_demo.py --simulator`: starts the simulator and the API wired together, no Twilio account, no tunnel; only an OpenAI key is needed. Without `--simulator` it uses real Twilio as before.

# Affected specs

* [/build/twilio-simulator.md](/build/twilio-simulator.md) - new, SIM-01…SIM-06.
* [/architecture/telephony.md](/architecture/telephony.md) - outbound calls, TEL-12…TEL-14.
* [/api/rest-api.md](/api/rest-api.md), [/architecture/call-modes.md](/architecture/call-modes.md) - the outbound phone endpoint and its relation to browser-simulated outbound.
* [/demo-data/claims-agent.md](/demo-data/claims-agent.md), [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md), [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md), [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md), [/product/use-cases.md](/product/use-cases.md), [/product/vision.md](/product/vision.md) - the Claims Follow-up Agent, its targets (MOCK-15), CLM-04, UC-02 (nine use cases).
* [/build/phone-demo.md](/build/phone-demo.md), [/build/runbook-phone.md](/build/runbook-phone.md) - `--simulator` (DEV-12), the simulator path.
* [/ui/calls.md](/ui/calls.md) - outbound phone calls in the detail header.
* [/product/scope.md](/product/scope.md), [/process/conventions.md](/process/conventions.md) (prefix `SIM`), indexes.

# Acceptance criteria

TEL-12…TEL-14 ([/architecture/telephony.md](/architecture/telephony.md)), SIM-01…SIM-06 ([/build/twilio-simulator.md](/build/twilio-simulator.md)), MOCK-15, CLM-04, DEV-12; UC-02 reworded.

# Tasks

1. Spec edits (first).
2. Platform: `POST /api/phone/outbound`, Twilio REST `Calls.create` helper, ring timeout, settings (`TWILIO_PHONE_NUMBER`, `OUTBOUND_RING_TIMEOUT_S`) — covers TEL-12…TEL-14.
3. Mock targets list, seed (agent, persona opening, use case, scenarios) — covers MOCK-15, CLM-04, UC-02.
4. `scripts/twilio_sim.py` with the browser phone — covers SIM-01…SIM-06.
5. `scripts/phone_demo.py --simulator` — covers DEV-12.
6. Tests, runbook, `.env.example`.

# Risks and rollout

* The simulator reproduces the Twilio behaviour the platform depends on (REST shapes, Media Stream events, signatures). It cannot prove Twilio's own behaviour (trial restrictions, carrier audio, latency); the first real call is still a by-hand check. Settings stay the same, so switching is `TWILIO_API_BASE` unset and real credentials.
* Browser audio is 8 kHz in the simulator to match the phone; quality is that of a phone call by design.
* An outbound call places a real call when pointed at real Twilio: `to` is always an explicit number, there is no list dialling, and nothing here adds consent or do-not-call handling, which stay out of scope.

# Out of scope

Dialer campaigns and lists, caller-ID management, consent and do-not-call handling, voicemail detection, SMS, buying numbers, other carriers.
