---
type: UI Spec
title: Agent console
description: The human specialist's view - live escalation queue, groundwork packet, transcript, accept and resolve with disposition.
status: stable
tags: [ui, console, escalation]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Layout (`/console/`)

* Left column: queue tabs **Waiting** (count) · **Mine** (accepted by me) · **Resolved today**. Each item: time waiting (live), reason badge (Safety = bad tone, pinned to top), intent, caller (masked), sentiment end.
* Main: selected escalation.
  * **Packet card** (top, large type): summary; intent; entities as chips; "Already tried" checklist; reason; sentiment `start → end` with trend arrow; suggested next action highlighted. While `packet_status: pending`, show a skeleton with "Preparing handoff notes…". Fallback packets show a small "Basic notes (AI summary unavailable)" label.
  * **Transcript** (collapsible, collapsed by default once the packet is ready).
  * Actions: **Accept** (assignee = name from a "Your name" field persisted in `localStorage`, default "Specialist"); after accept: disposition select + resolution note textarea (min 10 chars, hint: "What did you tell the caller? This teaches the agent.") + **Resolve**.
* New escalations arrive via SSE topic `console` with a soft chime (toggle) and a highlight animation.

# Acceptance

- **UI-12** — Given the console is open, when an escalation is created, then it appears in Waiting within 2 seconds without reload, and its packet fills in when ready.
- **UI-13** — Given an accepted escalation, when Resolve is clicked with a 5-character note, then the form shows the validation error and nothing is sent.
- **UI-14** — Given a safety escalation, then it is pinned to the top of Waiting with a red "Safety" badge.
