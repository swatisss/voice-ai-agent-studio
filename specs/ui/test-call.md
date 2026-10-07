---
type: UI Spec
title: Test call
description: Pick a published agent, then talk or type to it with a live transcript; the agent opens a voice call with its spoken welcome, and technical details are shown on demand.
status: stable
tags: [ui, voice, test-call]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Layout (`/test-call/?agent=…`)

* **Top row**: the **agent select** (published agents only), the version badge, the mode badge (Inbound / Outbound / Internal) and, at the right, the **Technical details** switch.
* **Handles line** under the top row: plain text "Handles: " followed by the titles of the use cases ([/product/use-cases.md](/product/use-cases.md)) served by the selected agent, separated by ` · `, from `GET /api/use-cases` matched on `agent_id`. There are no cards.
* **Call card** (left, main): header with the **Talk | Type** switch on the left and the Start / End button on the right; below it the conversation transcript — caller bubbles right, agent bubbles left, system notices centered (e.g. "Identity verified", "Escalated: policy required", "Call ended") — and the input area (message box in Type mode, mic button in Talk mode).
* **Right column**: **Live controls**, **Test script** and, only when Technical details is on, **Activity** and **Call**.

# Choosing what to test

* The agent select is the only way to choose. Changing it (when no call is running) updates `?agent=`, the Handles line and the Test script; it never starts a call.
* **Test script** card (collapsible, open by default): for each use case of the selected agent, in catalog order, its title as a plain subheading and its **starting phrase** — the first of the use case's sample phrases from `GET /api/use-cases` (for example "Is my health policy still active, and when does it renew?"). Nothing else is shown: demo callers (names, member IDs, dates of birth) are not listed on screen; they are in [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md) and the [demo script](/product/demo-script.md). A phrase is a button that fills the message box only while a chat is running; in every other situation it is plain text to read aloud (no disabled buttons).
* For an **outbound** agent the call card shows **Who should the agent call?** (a select of the agent's targets from `GET /api/outbound/targets`, each with its summary) and the start button reads **Place outbound call**. The agent speaks first with the persona's opening; the tester answers as the callee.

# Talk | Type

The switch sits in the call card header. It can be changed before a call starts and after it ends; while a call runs it is disabled with the hint "End the call to switch". It sets the call's channel (voice or text) and the start button label (**Start call** or **Start chat**).

# Technical details

A switch at the top right, **off by default** and remembered in the browser (`localStorage` key `test-call-technical`; the page works without storage).

* **Off**: no Activity card and no Call card. The transcript with its system notices, the outcome banner and Live controls are always shown.
* **On**: **Activity** — tool call chips in order (name, args summary, ✓/✕, duration) and knowledge searches with top result title + score or "No answer"; **Call** — call id (link to call detail), direction, status, turns, tokens, LLM cost, median latency.

Switching it on or off never restarts or disturbs a running call.

# Live controls

A **Live controls** card at the top of the right column (and shown before the call starts, where the values become call-start overrides):

* **Persona** select (the tenant's library personas; "Agent default" first). Changing it during a call sends `PATCH /api/calls/{id}/live`; the transcript shows the system notice "Persona switched to ..." and the next reply uses it (voice calls also change the TTS voice and speed).
* **Turn detection** (voice calls): the *Normal / Semantic* toggle, silence-threshold and extra-wait sliders, evaluator, and the interruption toggle. Changes are sent (debounced 300 ms) and apply to the next turn decision; a system notice records the change. For text calls the card is shown disabled with the hint "Turn detection applies to voice calls".
* Initial values come from the agent's default settings (`settings` in the call response) or from `/test-call/?persona=<id>`.

# Talk mode

1. **Start call** → `POST /api/calls {channel: "voice"}` → open WebSocket ([/api/voice-protocol.md](/api/voice-protocol.md)) and SSE `call:{id}`; ask for mic permission.
2. **The agent speaks first.** Once connected, the tester hears the welcome without saying anything — the persona's greeting and disclosure for inbound and internal agents, the persona's opening for outbound agents ([/architecture/call-modes.md](/architecture/call-modes.md)) — and the same text appears as the first agent message in the transcript. The test conversation starts after the welcome. The welcome is protected: speech during it, and the agent's own voice picked up by the microphone, neither interrupts it nor is answered ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), VO-08); the tester answers once it has ended. A headset avoids echo for the rest of the call.
3. While connected: big round mic button showing a live level meter; "Agent speaking" pulse while audio plays (including the welcome); **Hang up** button.
4. Transcript and activity come only from SSE `call.event` (single source of truth).
5. On `interrupt`, playback stops instantly.
6. On close code 4500, show "Voice is unavailable (speech provider key missing) — use Type mode".

# Type mode

1. **Start chat** → `POST /api/calls {channel: "text"}`; greeting shown.
2. Input + Send (Enter); while waiting, a typing indicator; replies come from the POST response and SSE events (de-duplicated by `seq`).
3. **End chat** button → `POST /end`.

After the call ends (either mode): outcome banner — "Resolved", "Escalated — waiting for a specialist", or "Ended" — and **Start new call**.

# Acceptance

- **UI-24** — Given the seeded business unit, when Test call opens, then there is no card gallery; the agent select lists the published agents; the "Handles:" line under it names the use cases of the selected agent; the Test script shows one starting phrase per use case of that agent and no demo caller details; and choosing another agent updates all three without starting a call.
- **UI-25** — Given an outbound agent, when a target is chosen and Place outbound call is clicked, then the first message in the transcript is the agent's opening addressed to that person, and the call is labelled outbound.
- **UI-23** — Given a running call, when the persona or the turn-detection mode is changed in Live controls, then a system notice appears in the transcript, the call continues without restarting, and the next agent reply (or turn decision) uses the new setting.
- **UI-31** — Given Test call, then the Talk | Type switch is in the call card header and not in the page's top row; when a call is running it is disabled; and when it is switched between calls the start button changes between Start call and Start chat.
- **UI-32** — Given a browser with no saved choice, when a call runs, then no Activity or Call card is shown while the transcript, system notices, outcome banner and Live controls are; when Technical details is switched on, both cards appear without restarting the call; and after a reload the choice is remembered.
- **UI-33** — Given Talk mode and an allowed microphone, when Start call is pressed, then the agent's welcome is heard and appears as the first agent message without the tester speaking, and the tester's answer after it ends is handled as the first turn; talking during the welcome does not cut it off.
- **UI-08** — Given a text call and Technical details on, when the agent calls a tool, then a tool chip appears in Activity with ✓ or ✕ before the reply bubble.
- **UI-09** — Given a voice call, when the user clicks Hang up, then the socket sends `hangup`, capture stops, and the outcome banner appears.
- **UI-10** — Given an escalation, then the transcript shows a system notice with the reason and the input is disabled except for "End".
