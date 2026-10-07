---
type: UI Spec
title: App shell
description: Left sidebar navigation, the Echo Mind Voice Agent Studio brand, business-unit switcher, routing scheme for the static export, and the shared API/SSE client.
status: stable
tags: [ui, shell, routing]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Layout

A fixed **left sidebar** (16 rem wide, full height, scrolls on its own if the window is short) next to the content, in the portal style of [/ui/design-system.md](/ui/design-system.md). There is no top header on viewports 768 px and wider.

* **Brand** (top of the sidebar): a generic mark, the product name **Echo Mind** and the caption "Voice Agent Studio" beneath it; the link to `/` has the accessible name "Echo Mind Voice Agent Studio home". The brand is the product's and does not change with the selected business unit. The browser tab title is "Echo Mind Voice Agent Studio".
* **Navigation** (icon + label, vertical, labels always visible): **Dashboard** `/`, **Agents** `/agents/`, **Personas** `/personas/`, **Test call** `/test-call/`, **Calls** `/calls/`, **Agent console** `/console/` (badge = waiting escalations), **Insights** `/insights/` (badge = clusters ready for a fix). The active item has an accent-soft background, accent text and a 4 px accent bar on its left edge.
* **Business-unit switcher** and provider status, pinned at the bottom of the sidebar. The switcher is a select listing `GET /api/tenants` (choice persisted in `localStorage` key `tenant`; default first tenant); each option shows only the unit part of the tenant name, the text after ` · ` (for example "Customer Support & Channels"), or the whole name when it has no ` · `. Provider health dots come from `/healthz` (Groq, OpenRouter, OpenAI, Deepgram: configured or not), each with its label.
* **Below 768 px** the sidebar is hidden and a slim sticky top bar shows the brand and a menu button; the button opens the same sidebar content as a drawer over the page, which closes after a navigation or on the close button.
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
- **UI-19** — Given any page, when navigating with the keyboard only, then the first Tab stop is "Skip to content", every navigation item and control shows a visible focus ring, and the active navigation item is highlighted with an accent bar and marked `aria-current="page"`.
- **UI-20** — Given a 375 px wide viewport, then the page has no horizontal scrollbar and the navigation is reachable through the menu button, which opens the sidebar as a drawer.
- **UI-28** — Given any page and any selected business unit, then the sidebar brand reads "Echo Mind" with the caption "Voice Agent Studio", the browser tab title is "Echo Mind Voice Agent Studio", the switcher options show only the unit part of each tenant name, and the text "Evergreen Health" appears nowhere in the sidebar, the top bar or the tab title.
- **UI-29** — Given a viewport of 1024 px or wider, then all seven navigation items are in a left sidebar in the order Dashboard, Agents, Personas, Test call, Calls, Agent console, Insights, each with its label; there is no top header; and the business-unit switcher and provider status are at the bottom of the sidebar.
