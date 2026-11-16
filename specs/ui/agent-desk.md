---
type: UI Spec
title: Agent Desk workspace
description: What a call-centre specialist sees - a five-item sidebar (Agent console, Escalated calls, Patterns, Knowledge, Agents), read-only pages for knowledge, agent settings and member memory, and comments on escalation patterns.
status: draft
tags: [ui, roles, console, learning]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Workspace

Signing in as a specialist lands on `/console/` ([/ui/agent-console.md](/ui/agent-console.md)). The sidebar ([/ui/app-shell.md](/ui/app-shell.md)) has five items: **Agent console** `/console/` (badge = waiting escalations), **Escalated calls** `/calls/`, **Patterns** `/patterns/`, **Knowledge** `/knowledge/`, **Agents** `/agents/view/`. No business-unit switcher (the unit's name is shown as plain text), no provider status dots, role badge **Agent Desk**. A specialist who opens any other path (Dashboard, Insights, Settings, the agent editor…) is sent to `/console/` with the toast "Not available for your role"; the API refuses the same requests ([/architecture/agent-desk.md](/architecture/agent-desk.md)).

* **Agent console.** The existing page. The "Your name" field is replaced by the signed-in name. The resolution hint reads "What did you tell the caller? This teaches the agent." and a resolve answers with the notice "Resolved. Thanks, this is now evidence for the learning loop."
* **Escalated calls** (`/calls/`). The call explorer limited to escalated calls: filters outcome and disposition only; caller, member reference, phone and email are masked. Call detail shows the transcript, packet, resolution note and analysis summary; there are no scorecard, cost, version-audit or conversation-routing cards, and no **Rescore**.
* **Patterns** (`/patterns/`, detail `/patterns/cluster/?id=…`). One card per cluster: name, what the callers asked, number of calls, status chip (**Watching 3 of 5**, **Ready for a fix**, **Fixed**). Detail: description, the escalated calls with what specialists told the caller (masked), and a **Comments** section: earlier comments (author, role, time) and a textarea "What do you tell callers about this?" with **Add comment** (10 to 1000 characters). Under the form: "Comments are used as evidence when the agent's fix is drafted." No cost, trend, proposal or approval controls.
* **Knowledge** (`/knowledge/`). A search box and the unit's articles (title, source type, updated); an article opens its full text. No add, upload, edit or delete controls. A banner "Read-only".
* **Agents** (`/agents/view/`). The unit's agents; an agent opens a read-only page of its published setup: persona, instructions, always/never rules, handoff rules, tools and skills with their descriptions, attached knowledge titles, and version history (version, date, who published, note). A banner "Read-only. Ask an admin to change an agent."
* **Member memory.** Reached from a call's member link; the page of [/ui/member-memory.md](/ui/member-memory.md) without **Export**, **Erase member** and **Restore**, with the reference masked.

Builders ([/ui/insights.md](/ui/insights.md)) see the same comments in a cluster's Evidence.

# Live voice panel

For an escalation whose call is in a media room ([/architecture/hosted-media-room.md](/architecture/hosted-media-room.md)) the console shows the **Live voice** strip and panel described in [/ui/agent-console.md](/ui/agent-console.md): **Take the call** (microphone permission asked then, with a headset hint), connection state, **Mute**, **Hang up**, a live two-sided transcript from `call.event` and `call.partial` (the specialist's own lines marked "You"), and **Resolve**. Identifiers in the transcript are masked as everywhere in Agent Desk. The page uses `livekit-client` with the token from `POST /api/escalations/{id}/voice/join`; the token is never displayed. If the customer hangs up, the panel says "Caller left" and the specialist may still resolve with a note.

# Acceptance

- **UI-77** — Given the specialist signed in, then the sign-in lands on `/console/`, the sidebar shows exactly Agent console, Escalated calls, Patterns, Knowledge and Agents, the badge Agent Desk and no business-unit switcher; opening `/insights/` or `/settings/` returns to `/console/` with the toast "Not available for your role".
- **UI-78** — Given the admin or reviewer signed in, then the sidebar has nine items (the ten of [/ui/app-shell.md](/ui/app-shell.md) without Agent console); with sign-in off it keeps the Agent console item.
- **UI-79** — Given the specialist on **Escalated calls**, then only escalated calls are listed, identifiers are masked, and the call detail has no scorecard, cost or Rescore control.
- **UI-80** — Given the specialist on a pattern, when they type a 60-character comment and click **Add comment**, then it appears in the list with their name and the textarea clears; a 9-character comment shows the validation message and sends nothing; the admin's cluster detail under Insights shows the same comment.
- **UI-81** — Given the specialist on **Knowledge** and **Agents**, then no control that adds, edits, deletes, saves or publishes is shown, the banner says the page is read-only, and an agent's page shows its published rules and tools.
- **LKH-25** — Given a voice escalation in `waiting`, then the console card shows "Live voice - customer waiting" with a running time and **Take the call**; an escalation without a media room shows neither.
- **LKH-26** — Given **Take the call** clicked by the specialist, then the microphone permission is asked, the escalation moves to Mine, the panel shows "Connected" once the room is joined, and the customer hears the AI's one introduction line and then the specialist.
- **LKH-27** — Given the connected panel, then both sides' words appear live in the transcript, **Mute** silences the specialist's microphone and shows "Muted", and **Hang up** leaves the room and shows the strip again with "Customer on hold".
- **LKH-28** — Given **Resolve** with a note under 10 characters, then the validation message shows and nothing is sent; with a valid note the call ends for the customer, the panel shows "Call ended" and the escalation moves to Resolved with the spoken lines in its transcript.
- **UI-82** — Given the specialist on a member's memory page, then the reference is masked and there is no Export, Erase or Restore control.
