---
type: UI Spec
title: App shell
description: Top-header navigation, business-unit switcher, routing scheme for the static export, and the shared API/SSE client.
status: stable
tags: [ui, shell, routing]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Layout

A sticky **top header** over the content, in the portal style of [/ui/design-system.md](/ui/design-system.md); no sidebar.

* **Brand**: a generic mark plus the business unit's brand name (the part of the selected tenant's name before ` · `), with the product caption "Voice Agent Studio" beneath it.
* **Navigation** (icon + label, horizontal): **Dashboard** `/`, **Agents** `/agents/`, **Personas** `/personas/`, **Test call** `/test-call/`, **Calls** `/calls/`, **Agent console** `/console/` (badge = waiting escalations), **Insights** `/insights/` (badge = clusters ready for a fix). The active item is underlined. Below 768 px the items collapse into a menu button that opens a dropdown panel.
* **Business-unit switcher** (select listing `GET /api/tenants`; choice persisted in `localStorage` key `tenant`; default first tenant) and provider health dots from `/healthz` (Groq, OpenRouter, Deepgram: configured or not) on the right.
* A **Skip to content** link is the first focusable element and jumps to the main region.

# Routing (static export)

No dynamic path segments. Detail pages use query parameters: `/agents/edit/?id=…`, `/calls/detail/?id=…`, `/insights/cluster/?id=…`, `/test-call/?agent=…`. All pages are client components.

# API client (`apps/web/lib/api.ts`)

* Base URL: `process.env.NEXT_PUBLIC_API_BASE ?? ""` (empty = same origin in production).
* Every request sends `X-Tenant-Id`; errors throw `ApiError {status, error, detail}` and surface as a toast.
* `useEvents(topics, handler)` hook wraps `EventSource` (`/api/events?tenant=…&topics=…`), reconnects with backoff, and closes on unmount or tenant change.
* Switching tenant reloads data on the current page.

# Acceptance

- **UI-01** — Given two tenants, when the user switches tenant, then the current page refetches and only that tenant's data is shown.
- **UI-02** — Given a waiting escalation is created, when any page is open, then the Agent console navigation badge increments without reload.
- **UI-19** — Given any page, when navigating with the keyboard only, then the first Tab stop is "Skip to content", every navigation item and control shows a visible focus ring, and the active navigation item is underlined and marked `aria-current="page"`.
- **UI-20** — Given a 375 px wide viewport, then the page has no horizontal scrollbar and the navigation is reachable through the menu button.
