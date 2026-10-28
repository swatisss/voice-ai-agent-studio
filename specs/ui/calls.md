---
type: UI Spec
title: Calls
description: Call explorer with filters and a call detail page showing transcript, tool calls, escalation packet and analysis.
status: stable
tags: [ui, calls]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Explorer (`/calls/`)

Filters: agent, outcome, channel, direction, feedback (Any · Not helpful · Helpful · No answer), "Include seeded history" (default on). Table: started, channel (a **Phone** badge when the call came in through Twilio), direction badge, agent version, caller (masked, e.g. `EVG-•••913`), intent, outcome badge, **feedback badge** ("Helpful" or "Not helpful" with a thumb icon, empty when the caller gave none), root cause, turns, LLM cost. Row click → detail.

# Detail (`/calls/detail/?id=…`)

* Header: outcome badge, channel, version, start/end, duration, end reason, cost, tokens; for a phone call also the dialled number and the caller's last four digits.
* Transcript (same rendering as test call) with tool calls inline as expandable rows (`JsonView` of args/result).
* **Escalation** card (if any): status, reason, disposition, resolution note, packet (same component as the console).
* **Caller feedback** card (when given): the rating as "Helpful" / "Not helpful", the comment and when it was given.
* **Memory** card (verified calls on agents with memory): **Memory used** (the facts and earlier calls the agent was given, each linked to its source) and **Memory updated** (what the agent added, superseded or confirmed after the call, with its reason; "Nothing new to remember" when empty), and a **Member memory** link to [/ui/member-memory.md](/ui/member-memory.md). For an identified call the header also shows "Identified by caller ID" and the attestation.
* **Analysis** card: intent, root cause, fixable, gap summary, caller goal, resolution summary, sentiment, cluster link.

# Acceptance

- **UI-46** — Given a verified call that loaded two facts and after which the agent superseded one, then the Memory card lists both loaded facts and the superseded fact with its replacement and reason, and Member memory opens that member's page for this agent.
- **UI-11** — Given a call with an escalation and analysis, when opened, then the packet, disposition, note and analysis fields are all visible.
- **UI-39** — Given a phone call and a browser voice call, then the explorer shows a **Phone** badge only on the phone call, and the phone call's detail header shows the dialled number and the caller's last four digits but no full caller number.
- **UI-36** — Given calls with and without feedback, then the explorer shows "Helpful" / "Not helpful" badges, filtering by Not helpful lists only those calls, and a call's detail page shows the caller's comment.
