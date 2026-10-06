---
type: Decision Record
title: ADR-0005 Single service
description: API, voice WebSocket, SSE, job worker, mock API and the statically exported web app run in one process and one Cloud Run service.
status: stable
tags: [decision, deployment]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Context

The demo must be reliable, cheap and quick to deploy. Separate services would need CORS, service-to-service auth, a shared message bus and a job queue service.

# Decision

* Next.js builds a static export; FastAPI serves it alongside `/api`, `/mock` and the voice WebSocket — one origin.
* The event bus is in-process; the job worker is an asyncio task in the same process.
* Cloud Run runs exactly one instance (`min=max=1`, CPU always allocated).

# Consequences

* No CORS or cross-service auth in production; one URL to share.
* No horizontal scaling in v1. Scaling later needs a CP: Redis/PubSub for events, a separate worker, and a sticky voice tier.
* Server-rendered Next.js features are unavailable; all pages are client components using query-string routes.
