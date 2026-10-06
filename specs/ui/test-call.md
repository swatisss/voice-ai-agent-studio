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
* Demo helper (collapsible): the seeded caller profiles (name, member ID, DOB) from [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md) for quick reference.

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

- **UI-08** — Given a text call, when the agent calls a tool, then a tool chip appears in Activity with ✓ or ✕ before the reply bubble.
- **UI-09** — Given a voice call, when the user clicks Hang up, then the socket sends `hangup`, capture stops, and the outcome banner appears.
- **UI-10** — Given an escalation, then the transcript shows a system notice with the reason and the input is disabled except for "End".
