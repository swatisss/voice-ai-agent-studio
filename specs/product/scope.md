---
type: Scope
title: v1 scope
description: What the v1 (hackathon) platform includes, what it excludes, and the non-goals.
status: stable
tags: [product, scope]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# In scope (v1)

* Multi-tenant data model with a tenant switcher (two seeded tenants).
* Agent builder: persona, policy, knowledge, tools, skills, model choice; publish immutable versions.
* Knowledge ingestion: pasted text/Markdown, file upload (`.md`, `.txt`, `.pdf`), URL, and **OKF bundle import**.
* HTTP tools with JSON-schema parameters, plus built-in tools (knowledge search, escalate, end call).
* **Test call from the browser** — voice (mic → agent → speaker) and text chat against the same agent runtime.
* Escalation engine with deterministic triggers and LLM judgment; groundwork packet; human agent console with accept/resolve and disposition.
* Fleet learning: per-call analysis, gap clustering, impact estimate, fix drafting (knowledge article or skill + tool), evaluation by simulated replay with a judge, approval → new agent version.
* Dashboard: calls, containment rate, escalated to human, response time, containment trend, escalations by root cause.
* The fourteen *Member & Sales Services* use cases of the fictional UK insurer Northgate Health ([/product/use-cases.md](/product/use-cases.md)), served by three inbound agents (Customer Care, Health Cover Sales, Claims & Pre-authorisation) behind a seeded front desk. Three call modes are available to any agent built in the Studio: inbound, **outbound** (the agent places the call, simulated in the browser) and internal (staff assistant).
* Seeded demo data ([/demo-data/northgate-health.md](/demo-data/northgate-health.md), [/demo-data/northgate-members.md](/demo-data/northgate-members.md)): members, policies and payments, documents, Digital GP slots, cash plans, health claims, pre-authorisations, specialists, a quote rating table and underwriting rules, knowledge articles, 123 historical calls. The Oakhaven Dental kit installs into the same business unit on demand.
* Mock healthcare and insurance business API served by the platform itself.
* **Inbound phone calls** through Twilio Media Streams to a published agent (one number per agent, IVR context, optional redirect of the live call to a person on hand-off), verifiable locally through a tunnel or a no-account simulator ([/architecture/telephony.md](/architecture/telephony.md)).
* An **optional realtime speech-to-speech voice pipeline** (OpenAI Realtime) chosen per agent in the Studio; the seeded Northgate agents use the Deepgram cascade ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)).
* A **public, key-authenticated API** per tenant (`/v1`) for tenant backends: text, voice over WebSocket, a Twilio-format media stream for any carrier, and WebRTC; per-key rate limits; signed webhooks ([/api/public-api.md](/api/public-api.md)).
* **Supervisor routing**: a front desk and a supervisor pick the agent from an automatically synced capability catalog; agents transfer conversations to each other ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)).
* **Studio sign-in with two roles**: an admin and a reviewer (the human in the loop); only an admin can change what callers hear ([/architecture/studio-auth.md](/architecture/studio-auth.md)).
* **English and Hindi with switching mid-call** for agents on the realtime pipeline, and a Hindi-aware safety screen on every agent ([/architecture/languages.md](/architecture/languages.md)).
* **Contact tools on every agent**: during any call or chat the agent can send the caller details by email (Brevo), SMS or an automated message call (Twilio), to a verified member's registered contact or an address the caller gives and confirms; an outbox stands in when no provider is configured ([/architecture/contact-tools.md](/architecture/contact-tools.md)).
* A **Compliance evidence** page: each healthcare control, the regulation it supports and the tests that prove it ([/product/compliance-evidence.md](/product/compliance-evidence.md)).
* Local dev with zero infrastructure (SQLite); GCP Cloud Run deployment.
* Spec-driven development tooling (`spec_check.py`, git hooks, agent instructions).

# Out of scope (v1) — roadmap

* Telephony beyond inbound Twilio calls and Twilio-format media streams: carriers other than Twilio and the customer's own Asterisk (the carrier-adapter interface and the SIP paths are decided in [ADR-0013](/decisions/adr-0013-carrier-adapters-and-sip-paths.md); SIP through a Twilio trunk or SIP domain works today), IVR/CCaaS connectors (Genesys, Amazon Connect), buying or managing phone numbers from the app, warm transfer of live audio to a human (a redirect of the live call is in scope), DTMF input, call recording.
* SSO, user management, roles beyond admin and reviewer, per-business-unit permissions; API keys authenticate only the `/v1` API. OAuth, per-user tokens and browser-held keys.
* Audio recording storage and playback.
* PHI redaction pipeline, BAAs, audit log export, data retention policies.
* Languages other than English and Hindi; Hindi on the cascade pipeline; Hindi knowledge articles and Studio UI.
* Real payments or bank details (secure links are mocked), real underwriting rules or prices of any insurer, business and corporate cover.
* Real outbound dialing (phone calls placed by the platform): dialer, caller ID, consent and do-not-call management, voicemail detection (v1 simulates outbound calls in the browser); a phone callback that connects the person to an agent. Two-way SMS, WhatsApp and chat widgets for end customers (one-way messages from the contact tools are in scope).
* Horizontal scaling (v1 runs as a single instance; see [/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)).

# Non-goals

* Automatically deploying fixes without human approval.
* Optimizing away escalations that policy requires (complaints, disputes, cancellations, bereavement, safety, explicit human requests).
* Giving medical advice.
