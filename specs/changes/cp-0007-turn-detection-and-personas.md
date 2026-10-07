---
type: Change Proposal
title: CP-0007 Turn-detection modes and a persona library, configurable live from the UI
description: Choose how the agent decides the caller has finished speaking (normal silence detection or semantic detection) and which persona it uses - per agent, per test call, and changeable while a call is running - all from the UI.
status: stable
cp_state: implemented
tags: [voice, personas, ui]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Why

Turn-taking quality decides whether a voice agent feels natural. Callers pause mid-sentence while dictating a member number, or say "I need to check my... um..." and a pure silence timer cuts them off. Semantic end-of-turn detection (as offered by LiveKit's turn-detector and similar) waits when the caller is clearly not done. Teams must be able to pick the mode, tune it, compare it live, and do the same for the agent's persona (name, voice, speaking speed, tone) without code or redeploys.

# What changes

1. **Turn-detection settings** per agent (`voice.turn_detection`), edited on a new **Voice** tab of the builder and versioned on publish:
   * **Normal detection** (`vad`): the turn ends after a configurable silence.
   * **Semantic detection** (`semantic`): after the silence, the platform judges whether the caller finished (heuristic by default; optionally a fast LLM check). If not, it waits up to a configurable extra time for more speech.
   * Interruption (barge-in) on or off.
2. **Persona library**: personas become first-class tenant objects (name, voice, speed, greeting, disclosure, outbound opening, speaking style) managed on a new **Personas** page; agents reference one by id and snapshots embed the resolved persona.
3. **Dynamic, live changes**: the Test call page chooses persona and turn-detection settings before a call and **changes them while the call is running** (`PATCH /api/calls/{id}/live`); voice changes apply to the next spoken sentence, persona text applies from the next turn.
4. The platform keeps its own turn detection on Pipecat rather than moving to LiveKit (see [/decisions/adr-0006-turn-detection.md](/decisions/adr-0006-turn-detection.md)).

# Affected specs

New: [/architecture/turn-detection.md](/architecture/turn-detection.md), [/architecture/personas.md](/architecture/personas.md), [/decisions/adr-0006-turn-detection.md](/decisions/adr-0006-turn-detection.md), [/prompts/turn-end-check.md](/prompts/turn-end-check.md), [/ui/personas.md](/ui/personas.md).
Updated: [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), [/architecture/agent-runtime.md](/architecture/agent-runtime.md), [/architecture/llm-gateway.md](/architecture/llm-gateway.md), [/data/agent-config.md](/data/agent-config.md), [/data/data-model.md](/data/data-model.md), [/api/rest-api.md](/api/rest-api.md), [/ui/agent-builder.md](/ui/agent-builder.md), [/ui/test-call.md](/ui/test-call.md), [/ui/app-shell.md](/ui/app-shell.md), [/ui/design-system.md](/ui/design-system.md), [/process/conventions.md](/process/conventions.md), [/build/runbook-local.md](/build/runbook-local.md).

# Acceptance criteria

TD-01…TD-08, PER-01…PER-06, UI-21…UI-23.

# Tasks

1. Spec edits (done first).
2. Backend: personas table + API, config schema, snapshot resolution, call overrides, live endpoint, `turn` LLM role — covers PER-*, TD-08, DM-01.
3. Voice: `turn_detection` module, `TurnAggregator` rewrite, barge-in setting, live controls registry, TTS runtime update — covers TD-01…TD-07.
4. Seed library personas for the demo tenants.
5. Web: Personas page, Voice tab, persona selector in the builder, live controls on Test call — covers UI-21…UI-23.
6. Tests and baseline entries for the UI criteria.

# Risks and rollout

* Semantic detection trades latency for fewer cut-offs: the extra wait applies only when the caller seems unfinished; the default evaluator is local and free. The LLM evaluator adds one small model call per turn.
* Live TTS voice changes are verified only against Pipecat's settings-frame API (unit test), not with a live Deepgram connection.
* Out of scope: audio-based turn-detection models (candidate follow-up: Pipecat's Smart Turn), speech-to-text endpointing mode, per-tenant default turn settings.
