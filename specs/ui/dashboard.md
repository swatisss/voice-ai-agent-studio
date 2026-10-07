---
type: UI Spec
title: Dashboard
description: Four headline metrics (calls, containment rate, escalated to human, response time), containment trend, escalations by root cause and recent agent versions for the selected tenant.
status: stable
tags: [ui, dashboard]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Content (from `GET /api/dashboard/summary`)

1. **Stat row** (four tiles, in this order):
   * **Calls** - `totals.calls`.
   * **Containment rate** - `totals.containment_rate`, hint "resolved ÷ (resolved + escalated)".
   * **Escalated to human** - `totals.escalated`, hint "handed to a human reviewer".
   * **Response time** - median of `totals.latency_p50_ms` in seconds (`1.2 s`), hint "median time to first reply"; an empty placeholder when there is no data.

   The summary also carries `cost_saved_usd` and `avg_llm_cost_usd` ([/api/rest-api.md](/api/rest-api.md)); the dashboard does not display them.
2. **Containment by week** (line chart, last 6 weeks) with a marker per published agent version.
3. **Escalations by root cause** (horizontal bar chart, human labels per [/ui/design-system.md](/ui/design-system.md)).
4. **Top clusters** (table: name, escalations/week, label/status; no cost column) linking to Insights.
5. **Recent versions** (list: version, change note, date) — fix-driven versions show "From fix: …".

Live: refetch on `call.ended` and `agent.published` (debounced 2 s).

# Acceptance

- **UI-27** — Given seeded data, when the dashboard loads, then the stat row shows exactly four tiles in the order Calls, Containment rate, Escalated to human, Response time; the Escalated to human tile carries the hint "handed to a human reviewer"; and no tile shows cost saved or LLM cost.
- **UI-30** — Given seeded data with at least one cluster, when the dashboard loads, then the Top clusters table has exactly the columns Cluster, Esc./week and Status, and no dollar amount appears anywhere on the dashboard.
- **UI-03** — Given seeded data, when the dashboard loads, then containment rate equals resolved ÷ (resolved + escalated) over non-eval calls, shown as a whole percent.
- **UI-04** — Given a proposal is approved, when the dashboard is open, then the recent versions list shows the new version without reload.
