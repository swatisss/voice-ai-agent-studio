---
type: Component Spec
title: Agent runtime
description: The shared brain used by voice calls, text chat and simulations - turn loop, prompt assembly, built-in tools, call state, safety screen and escalation triggers.
status: stable
tags: [architecture, runtime]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Purpose

One implementation of "how the agent behaves", used by three channels:

| Channel | Driver | Output |
|---|---|---|
| `voice` | [Voice pipeline](/architecture/voice-pipeline.md) | text chunks → TTS |
| `text` | `POST /api/calls/{id}/messages` | full reply text |
| `simulation` | [Evaluation](/architecture/evaluation.md) | full reply text |

Behavior MUST NOT differ between channels except: voice may emit a short *filler* line before slow tool calls, and voice/text replies are kept short and speakable (no markdown, no lists).

# Session API (`voiceai.runtime.session.AgentSession`)

| Method | Behavior |
|---|---|
| `start() -> str` | Returns the greeting: persona greeting + disclosure. Records it as an `assistant` event. |
| `respond(user_text) -> AsyncIterator[str]` | Runs one turn (below), yielding reply text chunks as they stream. |
| `end(reason)` | Ends the call (`end_call`, `farewell`, `handoff`, `idle`, `max_duration`, `hangup`, `error`; see [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md)); sets `ended_at`; queues `analyze_call`. Idempotent. |
| `state` | Current `CallState` (below). |
| turn policy (below) | Events in, decisions out, for channels where an external model produces the words, such as the realtime speech-to-speech pipeline ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)). `respond()` applies the same policy with the platform's own text model. |

| `set_persona(persona)` | Replaces the persona used for the next turns (live switch), records a `system` event "Persona switched to ...", never repeats the greeting. See [/architecture/personas.md](/architecture/personas.md). |

A session is constructed from a `call` row and the **config snapshot** of the agent version (or a candidate config during evaluation). It never reads the agent's draft.

# Call modes

A session knows its agent's `mode` (`inbound`, `outbound`, `internal`) and, for outbound calls, the call `context`. `start()` returns the persona greeting plus disclosure for inbound and internal calls, and the rendered persona **opening** for outbound calls. The mode prompt is part of the system prompt. Identity verification state is never inferred from the context. See [/architecture/call-modes.md](/architecture/call-modes.md).

# Turn algorithm

1. Record the `user` event; increment `turns`.
2. **Ended?** If the call has ended, yield nothing.
3. **Escalated or farewell?** If the call is already escalated (a session that is escalated yet still open), yield the policy `holding_message` without calling the LLM. Otherwise, if the caller's turn is a **farewell phrase** ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), CE-02), yield the closing line "Thank you for calling. Take care!", end with reason `farewell` and make no LLM request.
4. **Safety screen** (if `policy.safety_screen`): case-insensitive match against the safety phrase list in [/architecture/escalation.md](/architecture/escalation.md). On match, yield the safety message, escalate with category `safety`, stop.
5. Build messages: system prompt from [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) + the last 30 conversation messages (user, assistant, tool calls and results).
6. Call the LLM gateway with role `realtime` (agent model override honored), streaming, with tool schemas for built-in tools + the agent's tools.
7. While the model requests tool calls (max **4 rounds** per turn):
   1. voice only: if this is the first round in the turn and filler is enabled, yield `"One moment while I check that."` once;
   2. execute all requested calls (concurrently), record `tool_call` and `tool_result` events, update state;
   3. call the LLM again with the results appended.
8. Stream the final assistant text; record the `assistant` event with latency (time to first chunk) and token usage.
9. **Post-turn triggers** (deterministic, see [/architecture/escalation.md](/architecture/escalation.md)): no-answer streak, tool-error streak, max turns. If one fires and the call is not yet escalated, yield the handoff message and escalate.
10. **End.** If the call was escalated in this turn (model decision, safety screen or post-turn trigger), end the session with reason `handoff` once the handoff message has been yielded (CE-01); otherwise, if the model called `end_call`, end it with reason `end_call` after yielding its final text.

If the LLM fails after gateway fallback, yield `"I'm sorry, I'm having trouble right now. Let me connect you with someone who can help."` and escalate with category `other`.

# Turn policy

The rules of the turn algorithm above, offered to a channel whose model speaks for itself. The channel reports **events**; the session records them and returns a **decision**. The channel never needs to know the order of the rules.

| Event | What the session does | Decision returned |
|---|---|---|
| **Caller turn** (final text) | records the `user` event, increments `turns`, resets the turn's tool-round count, applies steps 2–4 (ended, escalated/farewell, safety) | *say exact line* (holding message; closing line then *end* `farewell`; safety message, escalate `safety`, then *end* `handoff`), or *let the model answer* |
| **Tool call requested** (name, arguments, call id) | applies the 4-round limit, then step 7.2 (verification gate, execution, events, state, escalation) | *tool result* (JSON, `tool_round_limit` past the limit), with *refresh instructions* when the verification status changed the prompt |
| **Reply finished** (text, latency, usage, interrupted) — for a reply with no tool calls still running | records the `assistant` event (with `[interrupted]` when cut off) and usage, then steps 9–10 | *say exact line* (hand-off message, escalate, then *end* `handoff`) when a post-turn trigger fires; *end* `end_call`, preceded by *say exact line* "Thank you for calling. Take care!" when the model said nothing; otherwise *continue* |
| **Tools finished** (whether the model spoke) — all tool calls of a reply have returned | nothing new to record | after `escalate_to_human`, *say exact line* (hand-off message) then *end* `handoff`; after `end_call`, as for *reply finished*; otherwise *let the model continue* |

A reply whose tool calls are still running, a fixed line the platform chose, or a reply the platform cut off is reported as *reply finished* for its usage only; the decision for a reply with tools comes from *tools finished*, because a realtime service reports the reply done before the tools return. The channel carries out each decision by first stopping its model, then **committing** it: a caller-turn line is recorded only at commit, so a model reply cut off for it is stored before it (RV-08).

Defaults for the hand-off message ("I'm connecting you with a specialist.") and the closing line are defined once, in the session. Timing (welcome protection, silence, maximum duration) is not part of the turn policy.

# Built-in tools

| Name | Parameters | Effect |
|---|---|---|
| `search_knowledge` | `query: string` | Searches the agent's knowledge docs ([/architecture/knowledge.md](/architecture/knowledge.md)). Returns results or `{"no_answer": true}`. |
| `escalate_to_human` | `reason_category` (enum, see escalation spec), `reason_detail: string` | Marks the call escalated and returns `{"status":"escalated","say":<handoff_message>}`. The runtime then speaks the handoff message itself and ends the turn without another LLM round (deterministic wording, no extra latency); the call then ends with reason `handoff` (CE-01). |
| `end_call` | `summary: string` | Marks the call for ending after the reply. If the model produced no goodbye text in that turn, the runtime says "Thank you for calling. Take care!" |

Agent tools (HTTP) come from the version snapshot; see [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md). Name collisions with built-ins are rejected at tool creation.

# Call state (`CallState`)

| Field | Meaning |
|---|---|
| `turns` | caller turns so far |
| `verified` | identity verified in this call |
| `verified_member_ref` | e.g. `EVG-482913` (stored on `calls.caller_ref`) |
| `no_answer_streak` | consecutive `search_knowledge` calls returning `no_answer` |
| `tool_error_streak` | consecutive agent-tool calls returning an error |
| `tools_used` | ordered list of `{name, ok, summary}` — feeds the groundwork packet |
| `escalated` / `escalation_id` | set once |
| `end_requested` / `ended` | lifecycle |
| `tokens_in`, `tokens_out`, `cost_usd` | accumulated from gateway usage |

`no_answer_streak` resets when a search returns results; `tool_error_streak` resets on a successful agent-tool call.

# Acceptance

- **RT-01** — Given a published agent, when a text call starts, then the first assistant event is the persona greeting followed by the disclosure.
- **RT-02** — Given a session that is escalated but still open, when the caller speaks, then the reply is the holding message and no LLM request is made. (Calls normally end at the hand-off, CE-01.)
- **RT-03** — Given the model requests a tool, when the tool returns, then `tool_call` and `tool_result` events are stored in order and the model is called again with the result.
- **RT-04** — Given the model keeps requesting tools, when 4 rounds are reached in one turn, then the runtime stops calling tools and returns the model's text (or an apology) for that turn.
- **RT-05** — Given the model calls `end_call`, when the reply finishes, then the call is ended with reason `end_call` and an `analyze_call` job is queued.
- **RT-06** — Given the realtime LLM raises after fallback, when a turn runs, then the caller hears the apology line and the call is escalated with category `other`.
- **RT-07** — Given the same agent version and the same scripted LLM responses, when run via text and via simulation, then the stored event sequences are identical apart from channel and timestamps.
- **RT-08** — Given a session, when `end()` is called twice, then only one `analyze_call` job exists for the call.
- **~~RT-10~~** — Retired by CP-0016: `run_tool` and `record_turn` are no longer the session's interface; parity between the text loop and an externally driven channel is RT-15. Was: given the same scripted tool results, when a tool is run through `run_tool` and through the text turn loop, then the stored `tool_call`/`tool_result` events, the verification outcome and the escalation behavior are identical; and `record_turn` stores a `user` and an `assistant` event, increments `turns` and adds the reported usage to the call totals.
- **RT-11** — Given a session, when a caller turn event arrives while the call is escalated, is a farewell phrase, or contains a safety phrase, then the decision is to say the holding message, the closing line then end `farewell`, or the safety message then escalate `safety` and end `handoff`, respectively, and no model request is made; any other text returns *let the model answer*.
- **RT-12** — Given five tool-call events in one caller turn, then the first four run with their events stored and the fifth returns `tool_round_limit` without running; the count restarts with the next caller turn; a `verify_member` call that verifies the caller returns its result with *refresh instructions*.
- **RT-13** — Given a reply-finished event after which a post-turn trigger fires (ES-02, ES-03, max turns), then the decision is to say the hand-off message, the call is escalated once and then ends `handoff`; with no `policy.handoff_message` the line is "I'm connecting you with a specialist.".
- **RT-14** — Given the model called `end_call`, when the reply-finished event carries no spoken text, then the decision is to say "Thank you for calling. Take care!" and end `end_call`; when it carries text, the decision is to end `end_call` with nothing more said.
- **RT-15** — Given the same scripted caller turns, model replies and tool results, when driven through `respond()` and through the turn-policy events, then the stored event sequences (`user`, `assistant`, `tool_call`, `tool_result`, `system`), the call state and the escalation rows are identical apart from timestamps.
- **RT-09** — Given a turn that used the LLM, when it completes, then the call's token counts and `llm_cost_usd` increase by the gateway-reported usage.
