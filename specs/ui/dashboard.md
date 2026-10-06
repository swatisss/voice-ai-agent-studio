---
type: UI Spec
title: Dashboard
description: Containment trend, outcome totals, escalations by root cause, cost saved, latency and recent agent versions for the selected tenant.
status: stable
tags: [ui, dashboard]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Content (from `GET /api/dashboard/summary`)

1. **Stat row**: Calls · Containment rate · Escalated · Cost saved · Avg LLM cost per call · Median response latency.
2. **Containment by week** (line chart, last 6 weeks) with a marker per published agent version.
3. **Escalations by root cause** (horizontal bar chart, human labels per [/ui/design-system.md](/ui/design-system.md)).
4. **Top clusters** (table: name, escalations/week, est. weekly cost, label/status) linking to Insights.
5. **Recent versions** (list: version, change note, date) — fix-driven versions show "From fix: …".

Live: refetch on `call.ended` and `agent.published` (debounced 2 s).

# Acceptance

- **UI-03** — Given seeded data, when the dashboard loads, then containment rate equals resolved ÷ (resolved + escalated) over non-eval calls, shown as a whole percent.
- **UI-04** — Given a proposal is approved, when the dashboard is open, then the recent versions list shows the new version without reload.
