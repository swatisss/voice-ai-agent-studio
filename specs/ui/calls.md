---
type: UI Spec
title: Calls
description: Call explorer with filters and a call detail page showing transcript, tool calls, escalation packet and analysis.
status: stable
tags: [ui, calls]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Explorer (`/calls/`)

Filters: agent, outcome, channel, direction, feedback (Any · Not helpful · Helpful · No answer), "Include seeded history" (default on). Table: started, channel, direction badge, agent version, caller (masked, e.g. `EVG-•••913`), intent, outcome badge, **feedback badge** ("Helpful" or "Not helpful" with a thumb icon, empty when the caller gave none), root cause, turns, LLM cost. Row click → detail.

# Detail (`/calls/detail/?id=…`)

* Header: outcome badge, channel, version, start/end, duration, end reason, cost, tokens.
* Transcript (same rendering as test call) with tool calls inline as expandable rows (`JsonView` of args/result).
* **Escalation** card (if any): status, reason, disposition, resolution note, packet (same component as the console).
* **Caller feedback** card (when given): the rating as "Helpful" / "Not helpful", the comment and when it was given.
* **Analysis** card: intent, root cause, fixable, gap summary, caller goal, resolution summary, sentiment, cluster link.

# Acceptance

- **UI-11** — Given a call with an escalation and analysis, when opened, then the packet, disposition, note and analysis fields are all visible.
- **UI-36** — Given calls with and without feedback, then the explorer shows "Helpful" / "Not helpful" badges, filtering by Not helpful lists only those calls, and a call's detail page shows the caller's comment.
