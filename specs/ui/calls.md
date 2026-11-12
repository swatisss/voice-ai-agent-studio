---
type: UI Spec
title: Calls
description: Call explorer with filters and a call detail page showing transcript, tool calls, escalation packet and analysis.
status: stable
tags: [ui, calls]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Explorer (`/calls/`)

Filters: agent, outcome, channel, direction, feedback (Any · Not helpful · Helpful · No answer), "Include seeded history" (default on). Table: started, channel (a **Phone** badge when the call came in through Twilio), direction badge, agent version, caller (masked, e.g. `EVG-•••913`), intent, outcome badge, **feedback badge** ("Helpful" or "Not helpful" with a thumb icon, empty when the caller gave none), root cause, turns, LLM cost. Row click → detail. Calls that are segments of a conversation show a **Routed** badge (or **Transferred** for segment 2 and later) and the segment number; filter **Conversation** (any / routed only).

# Detail (`/calls/detail/?id=…`)

* Header: outcome badge, channel, version, start/end, duration, end reason, cost, tokens; for a phone call also the dialled number and the caller's last four digits.
* **Audit line** under the header (from `version_info`, CMP-03): "Answered by v{n} · published by {published_by or 'unknown'} on {date}" and, when the version came from a learning fix, " · from fix '{title}' approved by {decided_by}" linking to the proposal's cluster.
* Transcript (same rendering as test call) with tool calls inline as expandable rows (`JsonView` of args/result).
* **Escalation** card (if any): status, reason, disposition, resolution note, packet (same component as the console).
* **Caller feedback** card (when given): the rating as "Helpful" / "Not helpful", the comment and when it was given.
* **Memory** card (verified calls on agents with memory): **Memory used** (the facts and earlier calls the agent was given, each linked to its source) and **Memory updated** (what the agent added, superseded or confirmed after the call, with its reason; "Nothing new to remember" when empty), and a **Member memory** link to [/ui/member-memory.md](/ui/member-memory.md). For an identified call the header also shows "Identified by caller ID" and the attestation.
* **Scorecard** card ([/architecture/call-scoring.md](/architecture/call-scoring.md)): a red **Hard fail** banner naming the failed hard-gate checks when there are any; the score; measures (first response, p50/p95 latency, tool calls and errors, knowledge searches and no-answers); checks grouped by Outcome, Responsiveness, Knowledge, Tools, Memory and Safety, each with its text, a verdict badge (Pass / Fail / N/A / Unknown / Not judged), a *Code* or *Judge* tag, the reason, and evidence links that scroll the transcript to the cited events (chunks show their doc title and heading). Judge checks have **Agree** / **Disagree** controls; Disagree asks for the correct verdict and an optional note; the reviewer name is remembered in `localStorage`. **Rescore** queues a new scoring. "Not scored yet" shows while the job runs and is replaced on `scorecard.updated` without reload. Simulation calls (opened from a test run) show their card too, with a **Simulated** badge in the header and no **Rescore** (their test run scored them); reviews on them are allowed but never count in the Evaluation page's calibration.
* **Conversation** card (segments only, [/architecture/agent-transfer.md](/architecture/agent-transfer.md)): source (API, Playground, Phone), the conversation's segments in order (agent, outcome, link), how this segment was routed (method, confidence, reason) and, for a transferred segment, the previous agent's reason and summary. The transcript starts with the front-desk lines when the segment was routed.
* **Analysis** card: intent, root cause, fixable, gap summary, caller goal, resolution summary, sentiment, cluster link.

# Acceptance

- **UI-46** — Given a verified call that loaded two facts and after which the agent superseded one, then the Memory card lists both loaded facts and the superseded fact with its replacement and reason, and Member memory opens that member's page for this agent.
- **UI-48** — Given a scored call with a failed hard gate, then the call detail shows the Hard fail banner and the failing check with its reason; clicking its evidence scrolls to and highlights the cited transcript line; marking Disagree with verdict Pass shows the reviewer's verdict next to the judge's after reload.
- **UI-11** — Given a call with an escalation and analysis, when opened, then the packet, disposition, note and analysis fields are all visible.
- **UI-39** — Given a phone call and a browser voice call, then the explorer shows a **Phone** badge only on the phone call, and the phone call's detail header shows the dialled number and the caller's last four digits but no full caller number.
- **UI-36** — Given calls with and without feedback, then the explorer shows "Helpful" / "Not helpful" badges, filtering by Not helpful lists only those calls, and a call's detail page shows the caller's comment.
- **UI-61** — Given a conversation with two segments, then both calls show in the explorer with Routed / Transferred badges and segment numbers, and each detail page's Conversation card lists both segments with links, the routing method and confidence, and the transfer reason.
- **UI-72** — Given a call answered by a version the admin published by approving a fix, then the call detail's audit line reads "Answered by v2 · published by Alex Admin on …" followed by "from fix '…' approved by Alex Admin" with a link to the cluster; for a seeded call on a version without a publisher it reads "published by unknown".
