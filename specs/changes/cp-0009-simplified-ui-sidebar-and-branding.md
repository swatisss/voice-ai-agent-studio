---
type: Change Proposal
title: CP-0009 Simplified UI - left navigation, focused dashboard, Echo Mind branding
description: Move the navigation from the top header to a left sidebar, cut the dashboard stat row to the four metrics a voice-agent owner watches (calls, containment, escalated to human, response time), and name the product "Echo Mind Voice Agent Studio" instead of the demo company.
status: stable
cp_state: implemented
tags: [ui, dashboard, navigation, branding]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-07T00:00:00Z" }
---

# Why

Feedback from the product owner after seeing the portal look from [CP-0005](cp-0005-insurer-portal-theme.md):

* The dashboard stat row has six tiles. Two of them - **Cost saved** and **Avg LLM cost / call** - are not metrics they will show; they distract from the ones that matter for a *voice* agent, and the one that matters most (response time) sits last and is labelled generically.
* The Top clusters table also carries an "Est. weekly cost" column. Dollar figures are not something they will show, so the dashboard drops them entirely.
* **Escalated** does not say what happens to the call. Reviewers should read at a glance that these calls were handed to a human.
* Seven navigation items (Dashboard, Agents, Personas, Test call, Calls, Agent console, Insights) crowd the top bar; on mid-sized screens most labels are already hidden. They belong in a left-hand menu.
* The header shows the seeded demo company's name as the brand. The product should carry its own name: **Echo Mind Voice Agent Studio**.

# What changes

1. **Dashboard stat row** shows four tiles, in this order: **Calls**, **Containment rate**, **Escalated to human** (hint "handed to a human reviewer"), **Response time** (median time to first reply, e.g. `1.2 s`). The **Cost saved** and **Avg LLM cost / call** tiles are removed. The `GET /api/dashboard/summary` response is unchanged; the two cost fields are simply not shown.
   The **Top clusters** table loses its "Est. weekly cost" column and keeps Cluster, Esc./week and Status; no dollar amount remains on the dashboard.
2. **Left sidebar navigation** (viewport 768 px and wider): the brand, all seven navigation items (always with labels, active item highlighted with an accent bar, badges kept), and - pinned at the bottom - the business-unit switcher and provider status dots. The top header is removed. Below 768 px a slim top bar (brand + menu button) opens the same sidebar as a drawer. This reverses the "no sidebar" layout choice of CP-0005; the colors, tokens, pill buttons and cards stay.
3. **Product name**: the brand is "Echo Mind" with the caption "Voice Agent Studio" (accessible name and browser tab title: "Echo Mind Voice Agent Studio"). It no longer follows the selected business unit. The business-unit switcher lists only the unit part of each tenant name (the text after ` · `, e.g. "Customer Support & Channels"), so the demo company name no longer appears in the navigation chrome. One copy line on the test-call page ("an Evergreen colleague") becomes "a colleague".
4. **No behavior, API, data or prompt change.** Tenant names in the database and API are untouched.

# Affected specs

* [/ui/dashboard.md](/ui/dashboard.md) - four-tile stat row, Top clusters without the cost column; UI-27 and UI-30.
* [/ui/app-shell.md](/ui/app-shell.md) - sidebar layout, fixed product brand, business-unit labels; UI-19 and UI-20 reworded for the sidebar; UI-28 and UI-29.
* [/ui/design-system.md](/ui/design-system.md) - layout section and principles describe the sidebar and the product brand instead of the top header (tokens unchanged, so UI-18 is unaffected).
* [/ui/index.md](/ui/index.md), [/product/scope.md](/product/scope.md) - dashboard one-liners no longer mention cost saved.

# Acceptance criteria

* **UI-27** (new, [dashboard](/ui/dashboard.md)) - the four-tile stat row.
* **UI-30** (new, [dashboard](/ui/dashboard.md)) - Top clusters without a cost column, no dollar amounts on the dashboard.
* **UI-28** (new, [app shell](/ui/app-shell.md)) - product brand, tab title, business-unit labels, no demo company name in the chrome.
* **UI-29** (new, [app shell](/ui/app-shell.md)) - left sidebar on 768 px and wider.
* **UI-19**, **UI-20** (changed, [app shell](/ui/app-shell.md)) - "underlined" becomes "highlighted with an accent bar"; the mobile menu opens the sidebar drawer.
* UI-03 (containment rate calculation, covered by a backend test) and UI-18 (token contrast, automated) are unchanged and must still pass.

# Tasks

1. Spec edits (done in this CP).
2. Web, `apps/web/components/shell.tsx` and `apps/web/app/layout.tsx` - sidebar and mobile drawer, product brand, `<title>`, business-unit option labels - covers UI-19, UI-20, UI-28, UI-29. Replace the `brandOf` helper with one that returns the unit part of the tenant name.
3. Web, `apps/web/app/page.tsx` - four-tile stat row and labels, Top clusters without the cost column (drop the now-unused `money` import if nothing else uses it) - covers UI-27, UI-30, UI-03.
4. Web, `apps/web/app/test-call/page.tsx` - one copy line.
5. (Done) Verify in the browser at 375, 1024 and 1440 px in light and dark mode; add UI-27, UI-28, UI-29 and UI-30 to `scripts/acceptance-baseline.txt` (manual verification, as for UI-19/20); run `npm run build`, the backend tests (API untouched, UI-03 must pass) and `python scripts/spec_check.py --ci --base origin/main`.
6. Close: specs to `status: stable`, this CP to `cp_state: implemented`, `specs/log.md` entry.

# Risks and rollout

* Visual only; no migration. The Agent console and Insights badges (UI-02) move with the navigation and must keep updating live.
* A fixed product brand drops CP-0005's "each business unit looks like its own portal" idea. Tenants are still switchable and still labelled by their unit name.
* The demo company name still appears in the *seeded* content shown inside pages (agent greetings and descriptions, knowledge articles, member data). That is demo data, not UI chrome; see out of scope.

# Out of scope

* Renaming the demo company in seed data, agent prompts/greetings, knowledge articles, demo-data specs and the ~10 test files that assert on it - decided against; the seeded content keeps its demo company name.
* Renaming non-UI occurrences of "Voice Agent Studio" (README, API title, `X-Title` header, dev launcher banner).
* Cost figures on other pages (the Insights pages still show estimated cost) and the "Cost saved" row of the success-metrics table in [/product/vision.md](/product/vision.md); removing the cost fields from the dashboard API or the backend settings behind them.
* A p95 response-time tile (needs an API field) and any logo artwork.
