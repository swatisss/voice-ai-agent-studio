---
type: Scope
title: v1 scope
description: What the v1 (hackathon) platform includes, what it excludes, and the non-goals.
status: draft
tags: [product, scope]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# In scope (v1)

* Multi-tenant data model with a tenant switcher (two seeded tenants).
* Agent builder: persona, policy, knowledge, tools, skills, model choice; publish immutable versions.
* Knowledge ingestion: pasted text/Markdown, file upload (`.md`, `.txt`, `.pdf`), URL, and **OKF bundle import**.
* HTTP tools with JSON-schema parameters, plus built-in tools (knowledge search, escalate, end call).
* **Test call from the browser** — voice (mic → agent → speaker over a WebSocket), video (a LiveKit Cloud room carrying mic and camera, which the agent may ask to look at, and a talking avatar face for the agent when Simli is configured) and text chat, all against the same agent runtime.
* **Visual evidence intake** — the agent takes one frame when it calls `look_at_camera`, describes it with a confidence it may withhold, pins it as evidence, and leaves a case with a routing decision and a business-system ticket ([/architecture/visual-intake.md](/architecture/visual-intake.md)). Captured frames are stored under a 30-day retention window ([ADR-0010](/decisions/adr-0010-media-retention.md)).
* Escalation engine with deterministic triggers and LLM judgment; groundwork packet; human agent console with accept/resolve and disposition.
* Fleet learning: per-call analysis, gap clustering, impact estimate, fix drafting (knowledge article or skill + tool), evaluation by simulated replay with a judge, approval → new agent version.
* Dashboard: calls, containment rate, escalated to human, response time, containment trend, escalations by root cause.
* The nine *Customer Support & Channels* use cases ([/product/use-cases.md](/product/use-cases.md)) with five agents in three call modes: inbound, **outbound** (the agent places the call, simulated in the browser) and internal (staff assistant and facilities intake).
* Seeded demo data: members, policies, claims, coverage, documents and Green Card, renewals, onboarding, providers, internal reference data, knowledge articles, ~120 historical calls.
* Mock healthcare and insurance business API served by the platform itself.
* Local dev with zero infrastructure (SQLite); GCP Cloud Run deployment.
* Spec-driven development tooling (`spec_check.py`, git hooks, agent instructions).

# Out of scope (v1) — roadmap

* Telephony: SIP trunks, IVR/CCaaS connectors (Genesys, Amazon Connect, Twilio), phone numbers, warm transfer of live audio to a human.
* Authentication, SSO, RBAC (a tenant switcher stands in).
* Audio recording storage and playback. Storing *frames the agent looked at* is in scope and is not a precedent for storing the call ([ADR-0010](/decisions/adr-0010-media-retention.md)).
* **A face created from an uploaded photograph.** The agent's talking face itself is in scope ([/architecture/avatar.md](/architecture/avatar.md)), as a stock face from the vendor. Building one from a photo is unverified in the SDK and raises consent and impersonation questions, so it needs its own proposal ([ADR-0011](/decisions/adr-0011-avatar-simli.md)).
* **A live video stream to a model.** The agent looks on demand ([/architecture/visual-intake.md](/architecture/visual-intake.md)). Video does reach the service continuously while the camera is on, which [ADR-0009](/decisions/adr-0009-video-channel.md) and compliance rule 9 state plainly; no frame reaches a model unasked.
* **Generating images.** No code path in the product produces an image; the reference and sample images are checked in ([/architecture/imagery.md](/architecture/imagery.md), IMG-01).
* PHI redaction pipeline, BAAs, audit log export, data deletion on request. v1 has a retention *window* for media and no deletion-on-request path.
* Languages other than English.
* Real outbound dialing: dialer, caller ID, consent and do-not-call management, voicemail detection (v1 simulates outbound calls in the browser). SMS and chat widgets for end customers.
* Horizontal scaling (v1 runs as a single instance; see [/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)).

# Non-goals

* Automatically deploying fixes without human approval.
* Optimizing away escalations that policy requires (appeals, safety, explicit human requests).
* Giving medical advice.
