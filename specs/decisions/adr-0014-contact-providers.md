---
type: Decision Record
title: ADR-0014 Brevo for email, Twilio for SMS and message calls, an outbox by default
description: Contact tools send email through Brevo and SMS and automated message calls through Twilio, behind one small provider layer with an outbox when nothing is configured; a "call" reads a message aloud instead of connecting the person to the AI agent.
status: stable
tags: [decision, messaging, email, sms, telephony, twilio]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Context

Agents should send callers details by email, SMS or a phone call ([CP-0038](/changes/cp-0038-contact-tools.md)). The owner asked for free tools where possible. The platform already uses Twilio for inbound phone calls ([ADR-0008](adr-0008-telephony-and-realtime-voice.md)) and must run with no keys at all (tests, the scripted demo, a new laptop).

# Options

Email (free allowance, checked 2026-11-12 from public comparisons; providers change these often):

1. **Brevo** - 300 emails a day on a permanent free plan, no card; simple REST API with an API key.
2. **Resend** - 3,000 a month, at most 100 a day; clean API, verified domain needed.
3. **Mailjet** - about 6,000 a month, 200 a day.
4. **SendGrid / Mailgun** - no permanent free plan (trials only).

SMS and voice (no provider has a real free plan; trials give a few dollars of credit):

A. **Twilio** - already integrated; trial sends only to verified numbers; about $0.008 per US SMS, $0.014 per US call minute.
B. **Telnyx / Plivo** - roughly half Twilio's price; a new account and adapter.
C. **Exotel / MSG91** - Indian numbers; DLT registration for SMS.

"Call":

i. **Message call** - Twilio places the call with inline TwiML that reads the message; one REST request, no media stream, no public URL.
ii. **AI callback** - Twilio dials and streams the audio to the voice agent; needs a public URL, outbound consent and do-not-call rules, voicemail detection.

# Decision

Email through **Brevo** (1), SMS and calls through **Twilio** (A), calls as **message calls** (i). Each channel goes through one function per provider, chosen from the environment, with an **outbox** provider that records the message and delivers nothing when no provider is configured. Simulations and evaluations always use a `simulated` record and never a provider.

# Consequences

* Works out of the box with no accounts; real delivery is two settings per channel.
* Adding Telnyx, Plivo or an Indian provider later is one more provider function; the tools, guards and records stay.
* Message calls cannot answer questions; a callback with the AI agent is a later change and fits the carrier adapters of [ADR-0013](adr-0013-carrier-adapters-and-sip-paths.md).
* Brevo and Twilio receive message text and recipient addresses; production use needs agreements with them like every other processor ([/product/healthcare-compliance.md](/product/healthcare-compliance.md), production gaps).
