---
type: Component Spec
title: Turn detection
description: How the voice pipeline decides the caller has finished speaking - normal silence detection and semantic detection - its settings, evaluator rules, interruption control and live updates.
status: stable
tags: [architecture, voice, turn-detection]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Settings

Stored per agent in `config.voice.turn_detection` ([/data/agent-config.md](/data/agent-config.md)), overridable per call and changeable while a call runs.

| Field | Values | Default | Meaning |
|---|---|---|---|
| `mode` | `vad` · `semantic` | `vad` | **Normal detection** ends the turn after the silence threshold. **Semantic detection** also judges whether the caller is finished. |
| `min_silence_ms` | 200–2000 | 700 | Silence after the last speech before the turn may end (total, including the acoustic VAD stop of 200 ms). |
| `max_extra_wait_ms` | 0–4000 | 1500 | Semantic mode only: extra time to wait for more speech when the caller seems unfinished. 0 makes semantic behave like normal. |
| `evaluator` | `heuristic` · `llm` | `heuristic` | Semantic mode only: how "finished?" is decided. |
| `allow_interruptions` | boolean | `true` | Whether the caller can barge in while the agent is speaking. |

# Turn aggregation

`TurnAggregator` sits after speech-to-text and collects final transcripts into one caller turn. State: the text buffer, whether the caller is currently speaking (from VAD), and one timer.

1. Caller starts speaking → cancel the timer.
2. A final transcript arrives → append it; if the caller is not speaking, (re)start the timer.
3. Caller stops speaking (VAD, after 200 ms of silence) → (re)start the timer.
4. **Timer 1** fires after `max(50 ms, min_silence_ms − 200 ms)` with a non-empty buffer:
   * `vad` mode → dispatch the turn.
   * `semantic` mode → ask the evaluator. *Complete* → dispatch. *Not complete* → start **timer 2** for `max_extra_wait_ms` (0 → dispatch now).
5. **Timer 2** fires → dispatch regardless. New speech before it fires cancels it and the cycle restarts, so the continuation is merged into the same turn.

Settings are read from the call's live controls at every decision, so a change applies to the next decision without restarting the call.

# Heuristic evaluator

Input: the buffered caller text and the *expected slots* inferred from the agent's last message. Output: complete or not, with a reason.

1. **Expected slots.** If the agent's last message (lower-cased) contains `member id` → `member_id` (6 digits); `policy number` → `policy_number` (6 digits); `claim number` → `claim_number` (5 digits); `zip` → `zip` (5 digits); `date of birth` or `birthday` → `date_of_birth` (a month and a year). Several may apply.
2. **Digits** are counted from numerals and spoken digit words (`zero`…`nine`, `oh`). When a date of birth is also expected, only text before the first month name counts toward the member or policy number. Not enough digits → **incomplete** ("waiting for more digits").
3. **Date of birth** needs a four-digit year (1900–2099) or a spoken year (`nineteen`/`twenty` followed by a number word) plus a month name or number; otherwise **incomplete**.
4. **Trailing hold words.** If the text ends with `,`, `...`, `-`, or its last word is a conjunction, article, preposition, auxiliary or filler (`and but so because or if that which who the a an my our your is are was were to of for with about um uh umm er hmm like also then when while since as at in on by from i i'm i'd it's`) → **incomplete**.
5. Otherwise **complete**.

Known limitation: with both ID and date of birth expected and a date spoken without a month name, digits can be over-counted; the LLM evaluator covers this.

# LLM evaluator

Role `turn` ([/architecture/llm-gateway.md](/architecture/llm-gateway.md)) with the prompt [/prompts/turn-end-check.md](/prompts/turn-end-check.md), JSON `{"complete": bool}`, timeout 900 ms. Any error, invalid JSON or timeout falls back to the heuristic verdict for that turn.

# Interruptions

`BrainProcessor` handles caller speech while the agent speaks. With `allow_interruptions: true` the VAD start event cancels the in-flight reply and broadcasts an interruption (TTS stops, the browser flushes audio). With `false` nothing is interrupted: the caller's turn is held and answered after the agent finishes.

# Live controls

For each active voice call a `LiveControls` object (in-memory registry keyed by call id) holds the current turn settings and an optional voice-change callback. `PATCH /api/calls/{id}/live` updates it and persists the override in the call's metadata; the pipeline reads it on every decision. Persona changes are described in [/architecture/personas.md](/architecture/personas.md).

# Acceptance

- **TD-01** — Given `vad` mode with `min_silence_ms: 700`, when two final transcripts arrive and the caller then stays silent, then exactly one turn containing both texts in order is dispatched after the silence threshold.
- **TD-02** — Given `semantic` mode and the caller says "I would like to check on my claim and", when the silence threshold passes, then the turn is not dispatched; a continuation "it is C-20931." arriving within `max_extra_wait_ms` is merged and dispatched as one turn.
- **TD-03** — Given `semantic` mode and the agent last asked for a member ID, when the caller says "four eight two", then the turn waits; when they continue "nine one three", then the turn completes. A date of birth without a year waits; with a year completes.
- **TD-04** — Given `semantic` mode and an unfinished utterance, when `max_extra_wait_ms` elapses with no new speech, then the turn is dispatched anyway; with `max_extra_wait_ms: 0` it is dispatched at the silence threshold.
- **TD-05** — Given evaluator `llm` and the model call raising an error or returning invalid JSON, then the heuristic verdict is used and the turn still completes.
- **TD-06** — Given a live call in `vad` mode, when settings are changed to `semantic`, then the next decision uses semantic detection without restarting the call.
- **TD-07** — Given `allow_interruptions: false` and the agent speaking, when the caller speaks, then no interruption is broadcast and the reply is not cancelled; the caller's turn is answered after the agent finishes. With `true`, the reply is cancelled and an interruption is broadcast.
- **TD-08** — Given a config with `min_silence_ms: 100`, `max_extra_wait_ms: 9000` or an unknown `mode`, when saved, then the API returns 422.
