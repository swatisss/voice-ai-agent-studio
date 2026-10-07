---
type: UI Spec
title: Test call
description: Talk or type to a published agent from the browser with a live transcript, tool activity, call status and outcome.
status: stable
tags: [ui, voice, test-call]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Layout (`/test-call/?agent=…`)

* Top: agent select (published agents only) and version badge; mode tabs **Talk** | **Type**.
* Left (main): conversation transcript — caller bubbles right, agent bubbles left, system notices centered (e.g. "Identity verified", "Escalated: policy required", "Call ended").
* Right panel: **Activity** — tool call chips in order (name, args summary, ✓/✕, duration), knowledge searches with top result title + score or "No answer"; **Call** card: call id (link to call detail), status, turns, tokens, LLM cost, median latency.
* **Demo callers** (collapsible): the callers of the selected use case (name, member ID, date of birth, what to try), from `GET /api/use-cases`.

# Use-case gallery and outbound calls

* Above the call panel, a **gallery of use-case cards** ([/product/use-cases.md](/product/use-cases.md)), grouped under the heading *Customer Support & Channels*: icon, title, one-line summary, mode badge (Inbound / Outbound / Internal) and channel chips. Selecting a card selects its agent (and updates `?agent=`), shows its sample utterances as **Try saying** chips (clicking one fills the message box in Type mode) and its demo callers.
* For an **outbound** use case the call panel shows **Who should the agent call?** (a select of the agent's targets from `GET /api/outbound/targets`, each with its summary) and the start button reads **Place outbound call**. The agent speaks first with the persona's opening; the tester answers as the callee.
* Selecting a use case never starts a call by itself.

# Live controls

A **Live controls** card above the Activity panel (and shown before the call starts, where the values become call-start overrides):

* **Persona** select (the tenant's library personas; "Agent default" first). Changing it during a call sends `PATCH /api/calls/{id}/live`; the transcript shows the system notice "Persona switched to ..." and the next reply uses it (voice calls also change the TTS voice and speed).
* **Turn detection** (voice calls): the *Normal / Semantic* toggle, silence-threshold and extra-wait sliders, evaluator, and the interruption toggle. Changes are sent (debounced 300 ms) and apply to the next turn decision; a system notice records the change. For text calls the card is shown disabled with the hint "Turn detection applies to voice calls".
* Initial values come from the agent's default settings (`settings` in the call response) or from `/test-call/?persona=<id>`.

# Talk mode

1. **Start call** → `POST /api/calls {channel: "voice"}` → open WebSocket ([/api/voice-protocol.md](/api/voice-protocol.md)) and SSE `call:{id}`; ask for mic permission.
2. While connected: big round mic button showing a live level meter; "Agent speaking" pulse when audio plays; **Hang up** button.
3. Transcript and activity come only from SSE `call.event` (single source of truth).
4. On `interrupt`, playback stops instantly.
5. On close code 4500, show "Voice is unavailable (speech provider key missing) — use Type mode".

# Type mode

1. **Start chat** → `POST /api/calls {channel: "text"}`; greeting shown.
2. Input + Send (Enter); while waiting, a typing indicator; replies come from the POST response and SSE events (de-duplicated by `seq`).
3. **End chat** button → `POST /end`.

After the call ends (either mode): outcome banner — "Resolved", "Escalated — waiting for a specialist", or "Ended" — and **Start new call**.

# Acceptance

- **UI-24** — Given the seeded business unit, when Test call opens, then the gallery shows the seven use cases under "Customer Support & Channels", and selecting one selects its agent and shows its sample utterances and demo callers.
- **UI-25** — Given an outbound use case, when a target is chosen and Place outbound call is clicked, then the first message in the transcript is the agent's opening addressed to that person, and the call is labelled outbound.
- **UI-23** — Given a running call, when the persona or the turn-detection mode is changed in Live controls, then a system notice appears in the transcript, the call continues without restarting, and the next agent reply (or turn decision) uses the new setting.
- **UI-08** — Given a text call, when the agent calls a tool, then a tool chip appears in Activity with ✓ or ✕ before the reply bubble.
- **UI-09** — Given a voice call, when the user clicks Hang up, then the socket sends `hangup`, capture stops, and the outcome banner appears.
- **UI-10** — Given an escalation, then the transcript shows a system notice with the reason and the input is disabled except for "End".
