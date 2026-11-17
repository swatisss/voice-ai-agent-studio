---
type: UI Spec
title: Agent Desk workspace
description: What a call-centre specialist sees - a five-item sidebar (Agent console, Escalated calls, Patterns, Knowledge, Agents), read-only pages for knowledge, agent settings and member memory, and comments on escalation patterns.
status: stable
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

# The browser as a phone, and WhatsApp conversations

([CP-0051](/changes/cp-0051-twilio-phone-warm-handover.md), [CP-0052](/changes/cp-0052-whatsapp-via-twilio.md); the conversation panel itself is CP-0049's UI-86.)

* **Phone control** (header of the Agent console, specialist and admin; hidden when `GET /healthz` has `providers.twilio_voice_sdk: false`). A switch **Take calls in this browser** with a status chip: *Offline*, *Ready*, *Ringing*, *On a call*. Switching it on asks for the microphone, fetches a token from `POST /api/desk/phone-token`, registers the Twilio Device and sends `PUT /api/desk/phone-presence` every 30 seconds; switching it off, closing the page or a registration error sets *Offline*. Specialists who do not switch it on are never rung in the browser.
* **Incoming handover.** While *Ringing* a banner shows the packet card (summary, intent, reason, suggested next action, identifiers masked) with **Answer** and **Decline**. After answering, a call bar shows the timer, **Mute** and **Hang up**; the escalation is accepted for the signed-in specialist (their name is the assignee) and the console shows it as *Accepted*. A **Recorded** badge shows when the call is recorded. When the call ends the resolve form opens as usual.
* **Human portion in the transcript.** After a recorded handover is transcribed, the call detail (Agent Desk and Calls) shows the specialist's conversation under a divider "Specialist call" with speakers **Caller** and **Specialist** (the specialist's name); a mono recording labels every line **Specialist call (mixed)**.
* **WhatsApp conversations** use CP-0049's conversation panel with a **WhatsApp** badge, a countdown "Reply window: 3 h 12 min left" (amber under 1 hour) and, when the window is closed, a notice "The 24-hour window has closed. Your reply will be sent after the customer answers a short message we send now." with the composer enabled; each message shows its delivery state (*Sent*, *Delivered*, *Read*, *Failed*); an opted-out thread disables the composer with "The customer has stopped messages." The customer is shown as `wa-…{last4}`.

# Acceptance

- **UI-77** — Given the specialist signed in, then the sign-in lands on `/console/`, the sidebar shows exactly Agent console, Escalated calls, Patterns, Knowledge and Agents, the badge Agent Desk and no business-unit switcher; opening `/insights/` or `/settings/` returns to `/console/` with the toast "Not available for your role".
- **UI-78** — Given the admin or reviewer signed in, then the sidebar has nine items (the ten of [/ui/app-shell.md](/ui/app-shell.md) without Agent console); with sign-in off it keeps the Agent console item.
- **UI-79** — Given the specialist on **Escalated calls**, then only escalated calls are listed, identifiers are masked, and the call detail has no scorecard, cost or Rescore control.
- **UI-80** — Given the specialist on a pattern, when they type a 60-character comment and click **Add comment**, then it appears in the list with their name and the textarea clears; a 9-character comment shows the validation message and sends nothing; the admin's cluster detail under Insights shows the same comment.
- **UI-81** — Given the specialist on **Knowledge** and **Agents**, then no control that adds, edits, deletes, saves or publishes is shown, the banner says the page is read-only, and an agent's page shows its published rules and tools.
- **UI-82** — Given the specialist on a member's memory page, then the reference is masked and there is no Export, Erase or Restore control.
- **UI-91** — Given the specialist on the Agent console with the Voice SDK configured, when they switch on **Take calls in this browser**, then the microphone is requested, the chip shows *Ready*, presence is sent every 30 seconds, and switching off or an error shows *Offline*; with `providers.twilio_voice_sdk: false` the control is not shown.
- **UI-92** — Given a ringing handover, then a banner shows the masked packet with **Answer** and **Decline**; after **Answer** the call bar shows the timer, **Mute** and **Hang up**, the escalation shows as *Accepted* by the signed-in specialist, a **Recorded** badge appears when the agent records handovers, and **Decline** leaves the call ringing for others.
- **UI-93** — Given a call whose handover recording has been transcribed, then the call detail shows the specialist conversation under "Specialist call" with speakers Caller and Specialist (mixed for a mono recording), and a call without a handover shows no such section.
- **UI-94** — Given an escalated WhatsApp conversation, then the panel shows the WhatsApp badge, the reply-window countdown (amber under 1 hour), per-message delivery states and the customer as `wa-…{last4}`; for an `opted_out` thread the composer is disabled with the explanation.
- **UI-95** — Given a WhatsApp conversation whose window has closed, when the specialist sends a reply, then the notice about the follow-up message is shown and the reply appears as *Queued* until the customer answers; with a sandbox sender the composer is disabled with "Sandbox: replies only inside the 24-hour window".