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
* The seven *Customer Support & Channels* use cases ([/product/use-cases.md](/product/use-cases.md)) with four agents in three call modes: inbound, **outbound** (the agent places the call, simulated in the browser) and internal (staff assistant).
* Seeded demo data: members, policies, claims, coverage, documents and Green Card, renewals, onboarding, providers, internal reference data, knowledge articles, ~120 historical calls.
* Mock healthcare and insurance business API served by the platform itself.
* Local dev with zero infrastructure (SQLite); GCP Cloud Run deployment.
* Spec-driven development tooling (`spec_check.py`, git hooks, agent instructions).

# Out of scope (v1) — roadmap

* Telephony: SIP trunks, IVR/CCaaS connectors (Genesys, Amazon Connect, Twilio), phone numbers, warm transfer of live audio to a human.
* Authentication, SSO, RBAC (a tenant switcher stands in).
* Audio recording storage and playback.
* PHI redaction pipeline, BAAs, audit log export, data retention policies.
* Languages other than English.
* Real outbound dialing: dialer, caller ID, consent and do-not-call management, voicemail detection (v1 simulates outbound calls in the browser). SMS and chat widgets for end customers.
* Horizontal scaling (v1 runs as a single instance; see [/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)).

# Non-goals

* Automatically deploying fixes without human approval.
* Optimizing away escalations that policy requires (appeals, safety, explicit human requests).
* Giving medical advice.
