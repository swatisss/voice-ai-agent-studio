---
type: Change Proposal
title: CP-0017 Effective call settings
description: One place resolves a call's effective persona, turn detection and pipeline from the version config, call-start and live overrides; live changes go through the session only and the voice pipeline follows them.
status: stable
cp_state: implemented
tags: [architecture, runtime, personas, turn-detection]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Why

The architecture review of 2026-10-27 found call settings resolved in several places:

* `live.py` mixes four things in 66 lines: the in-memory `LIVE` registry of `LiveControls`, pure config readers (`persona_dict`, `pipeline_of`, `effective_turn`), the response shape (`settings_view`) and a database-backed view (`effective_settings`).
* The persona override (live, else call-start, else snapshot) is resolved twice: `live.effective_settings` and `AgentSession.open`.
* `routes/calls.py` `live_settings` changes the session **and** reaches into the pipeline's `LiveControls` (`controls.on_voice`, `controls.turn`), so the route must know how the voice pipeline consumes changes.

# What changes

* **Effective call settings** is one resolution ([/architecture/personas.md](/architecture/personas.md), [/architecture/turn-detection.md](/architecture/turn-detection.md)): version config + call-start overrides + live overrides + the persona row → persona, turn detection, pipeline (and, with CP-0015, the admission plan's key source). The session and the read views (`POST /api/calls`, `GET /api/calls/{id}`, `PATCH .../live`) all use it, so they always agree.
* `PATCH /api/calls/{id}/live` talks to the session only. The session records the change (events, metadata) and **notifies** the running voice pipeline, which applies the new voice and turn settings itself. The route no longer touches `LiveControls`.
* No observable behaviour changes: PER-03, PER-04, TD-06, RV-15 and the `settings` shape in [/api/rest-api.md](/api/rest-api.md) stay as they are.

# Affected specs

* [/architecture/turn-detection.md](/architecture/turn-detection.md) - Live controls: the session is the only writer; the pipeline subscribes; TD-09
* [/architecture/personas.md](/architecture/personas.md) - effective persona resolved in one place; PER-07

# Acceptance criteria

New: TD-09, PER-07. Unchanged: PER-03, PER-04, TD-06, RV-15.

# Tasks

1. Spec edits (this CP).
2. An effective-call-settings module (pure resolution plus one loader), used by `AgentSession.open`, `session.settings()` and the call routes; `settings_view` and `effective_settings` folded in — covers PER-07.
3. Session change notification; the voice pipeline (cascade brain and TTS) subscribes when it starts and unsubscribes at the end; `live_settings` stops using `LIVE` — covers TD-09, TD-06, PER-04.
4. Tests: resolution table test; a live-change test that checks the pipeline receives the new voice and turn settings through the subscription.

# Risks and rollout

* Independent of CP-0015 and CP-0016, but touches `routes/calls.py` like CP-0015: implement after it to avoid conflicts.
* The `LIVE` registry stays the single process-global for active calls (single service, [/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)); a subscription that outlives its call would leak, so unsubscribe on every end path.

# Out of scope

* Live changes on realtime calls (still 409 `realtime_pipeline`, RV-15).
* New live-changeable settings.
