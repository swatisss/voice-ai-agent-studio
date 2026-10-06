---
type: UI Spec
title: App shell
description: Navigation, tenant switcher, routing scheme for the static export, and the shared API/SSE client.
status: stable
tags: [ui, shell, routing]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Layout

Left sidebar (collapsible on narrow screens) + top bar + content.

* Sidebar items (icon + label): **Dashboard** `/`, **Agents** `/agents/`, **Test call** `/test-call/`, **Calls** `/calls/`, **Agent console** `/console/` (badge = waiting escalations), **Insights** `/insights/` (badge = clusters ready for a fix).
* Top bar: product name "Voice Agent Studio", **tenant switcher** (select listing `GET /api/tenants`; choice persisted in `localStorage` key `tenant`; default first tenant), provider health dots from `/healthz` (Groq, OpenRouter, Deepgram: configured or not).

# Routing (static export)

No dynamic path segments. Detail pages use query parameters: `/agents/edit/?id=…`, `/calls/detail/?id=…`, `/insights/cluster/?id=…`, `/test-call/?agent=…`. All pages are client components.

# API client (`apps/web/lib/api.ts`)

* Base URL: `process.env.NEXT_PUBLIC_API_BASE ?? ""` (empty = same origin in production).
* Every request sends `X-Tenant-Id`; errors throw `ApiError {status, error, detail}` and surface as a toast.
* `useEvents(topics, handler)` hook wraps `EventSource` (`/api/events?tenant=…&topics=…`), reconnects with backoff, and closes on unmount or tenant change.
* Switching tenant reloads data on the current page.

# Acceptance

- **UI-01** — Given two tenants, when the user switches tenant, then the current page refetches and only that tenant's data is shown.
- **UI-02** — Given a waiting escalation is created, when any page is open, then the Agent console sidebar badge increments without reload.
