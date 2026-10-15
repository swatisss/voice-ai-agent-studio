---
type: Component Spec
title: Live session engine
description: "How a video call runs on one Gemini Live session whose avatar video and voice arrive together: what the session does, what stays ours and runs on top of it, how the camera is pulled, and how it fails."
status: draft
tags: [architecture, video, avatar, gemini, live, latency]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# What this is for

A call that feels live needs few hops. The LiveKit engine has five in series between the caller's voice and the agent's face. The Live engine has one: a speech-to-speech session on Vertex AI that listens, thinks and speaks, and, when asked for video, returns the avatar's face and voice as **one muxed stream**, so they share a clock and no lip-sync stage exists. The decision, the evidence and the alternatives are in [ADR-0012](/decisions/adr-0012-gemini-live-avatar.md); the browser wire is [/api/live-protocol.md](/api/live-protocol.md).

It is a second **engine** for `channel: "video"`. The first, `livekit`, is unchanged ([/api/media-protocol.md](/api/media-protocol.md), [/architecture/avatar.md](/architecture/avatar.md)). Voice and text calls are unaffected.

# Topology

```
browser mic ─PCM16 16k─▶ WS /api/live/{call_id} ─▶ relay (voice module) ─▶ LiveAgent port ─▶ Gemini Live session
browser player ◀─ fMP4 (face + voice, base64) ◀──┘        │                                    (Vertex AI)
                                                          ├── tool calls ─▶ conversation contract (our executor)
                                                          ├── transcripts ─▶ call events (user / assistant)
                                                          └── frame request ─▶ browser ─▶ FrameSource ─▶ evidence (vision role)
```

The relay is in the `voice` module. It depends on the `LiveAgent` **port** ([/architecture/modular-structure.md](/architecture/modular-structure.md)), never on Google's SDK, which is imported in one adapter only (GL-13). The relay forwards media **verbatim**: it does not decode, re-encode or buffer it beyond one chunk (GL-03).

# The session

| Setting | Source |
|---|---|
| Model | `GEMINI_LIVE_MODEL`, never a literal in code. Default is the id the reference uses; confirmed or corrected by the spike |
| Credentials | Application Default Credentials for the Vertex AI project in `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION`. An API key is not used. Nothing credential-shaped leaves the process (GL-14) |
| Output | Video with an avatar when `GEMINI_AVATAR_NAME` is set; otherwise audio only |
| Voice | `GEMINI_LIVE_VOICE`. One voice and one avatar serve every agent in this change |
| System instruction | The agent's rendered system prompt ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md)) followed by [/prompts/live-session-addendum.md](/prompts/live-session-addendum.md) |
| Tools | The agent's built-ins and tools as function declarations, **non-blocking**, so the face keeps talking while a tool runs. `look_at_camera` is declared only when the call has a camera |
| Input | The caller's microphone as 16 kHz PCM; input and output **transcription** on; caller speech interrupts the session |

An **availability** check mirrors AV-01: the project and location are set, the SDK is installed and credentials can be found. Anything less makes the engine unavailable, which is not an error: the call falls to the LiveKit engine (GL-01).

# What stays ours

The session is the brain's voice, but the product's rules do not move into a prompt.

| Concern | How it holds on this engine |
|---|---|
| Tools and the identity gate | A function call from the session is executed by the conversation module's tool executor, the same one the text runtime uses. `tool_call` and `tool_result` events are recorded in order and call state is updated. A tool marked `requires_verification` is refused before the caller is verified, exactly as today ([/product/healthcare-compliance.md](/product/healthcare-compliance.md) rule 3). The result goes back to the session; when it carries `say`, as escalation does, the session is told to speak those words (GL-06). |
| Transcripts | Each finished caller utterance and each finished agent reply is recorded as a `user` / `assistant` event, so analysis, feedback, the console and the explorer need no change. `assistant` events carry `latency_ms` from end of caller speech to the first media chunk (GL-07). |
| Safety screen | Each final caller transcript is checked against the safety phrase list ([/architecture/escalation.md](/architecture/escalation.md)). A match escalates with category `safety`, records the fixed safety message, interrupts whatever the session was saying and tells it to speak that message; the call then ends `handoff`. **The wording of the spoken audio is not guaranteed verbatim**; the recorded and displayed text is (GL-08). |
| Welcome | On connect the relay tells the session to speak the greeting from `AgentSession.start()` exactly once. It is protected as VO-08 is: caller audio is not forwarded and caller turns heard are dropped until the welcome finishes, or 15 s pass (GL-09). |
| Ending | `end_call`, a farewell, `escalate_to_human`, idle and maximum duration end the call with the same reasons as ever. The closing words finish first (at most 10 s, CE-06), then the browser receives `end` and the session closes within 5 s (GL-10). The silence reminder and closing line are spoken by instructing the session, on the same clocks as CE-04 and CE-05. |
| Cost | The session's usage is added to the call's tokens and `llm_cost_usd`, priced from configuration. A model with no price counts as zero and logs a warning (GL-15). |

Turn-detection modes and live persona switching are **not available** here: turn-taking is the session's own, and the persona is the prompt plus the one configured voice (LV-06).

# The camera is pulled

The caller's camera never streams to us and never reaches the session. When the model calls `look_at_camera`, the relay sends the browser a `frame_request`; the browser answers with **one** JPEG, and the relay hands it to the `evidence` module through the `FrameSource` port exactly as the LiveKit engine does ([/architecture/visual-intake.md](/architecture/visual-intake.md)). The description still comes from the `vision` role, the observation still carries a confidence it may withhold, and the pinned evidence, case and routing are unchanged. No answer within 3 s, or a camera that is off, is a declined look (GL-11).

This is stronger than the LiveKit engine, where video streams to a media server whenever the camera is on (compliance rule 9): here **nothing leaves the browser unless a look asked for it.**

# When it fails

* **No avatar** (not configured, or the vendor refuses the avatar for this project): the session is opened audio-only, the browser is told `avatar: false` and shows the placeholder tile. If the avatar is refused after the session opens, the relay reconnects once audio-only. If the browser cannot play the stream it asks for the same (GL-05).
* **No session** (credentials, region, quota): the call ends with reason `error`, the browser receives `end` with a reason it can show, and the transcript so far is kept. It does not hang; nothing is spoken by a second engine (GL-12).
* **Mid-call drop:** the same. The relay never retries a session silently, because the caller would hear an agent that had forgotten the conversation.

# Latency

The intent is that the face answers within about a second of the caller finishing. That is a target, not a criterion: it depends on the vendor, is unmeasured, and is established by the spike (CP-0018, T36) and by hand. The relay adds no buffering of its own (GL-03).

# Acceptance

- **GL-01** — Given `VIDEO_ENGINE` is `auto` and Vertex AI project, location, SDK and credentials are all present, when `POST /api/calls` is called with `channel: "video"`, then `media.engine` is `gemini_live` and carries a socket path and `avatar`, with no LiveKit token; and given any of them absent, then the call is created on the `livekit` engine when LiveKit is configured and as `video_unavailable` otherwise; and given `VIDEO_ENGINE` is `livekit`, then the LiveKit engine is used whatever else is configured.
- **GL-02** — Given a call on the Live engine, when its session is opened, then the model id comes from configuration, video output is requested with the configured avatar only when one is configured, the system instruction is the agent's system prompt followed by the live addendum, every tool is declared non-blocking, and `look_at_camera` is declared only on a call with a camera.
- **GL-03** — Given the session produces media chunks and the caller sends microphone audio, when the relay forwards them, then each chunk reaches the other side unchanged, in order, and the relay holds no more than the chunk in flight.
- **GL-04** — Given the session reports it was interrupted, when the relay sees it, then the browser receives `interrupt` and nothing queued before it is delivered after it; and given a tool result arrives later, then it is still returned to the session.
- **GL-05** — Given the avatar is not configured, or the vendor refuses it, or the browser asks for it off, then the session runs audio-only, the browser is told `avatar: false`, the call continues, and the audio-only open is attempted at most once more for the same call.
- **GL-06** — Given the session requests tools, when they are executed, then each runs through the conversation executor with `tool_call` and `tool_result` events recorded in order; and given a `requires_verification` tool before the caller is verified, then it is refused and the refusal is returned to the session; and given a result with `say`, then the session is told to speak it.
- **GL-07** — Given finished caller and agent transcripts, when the turn completes, then one `user` and one `assistant` event are recorded in order, `turn_count` increases, and the `assistant` event carries `latency_ms`.
- **GL-08** — Given a final caller transcript that matches the safety phrase list, then the call is escalated with category `safety`, the fixed safety message is recorded and sent to the browser, the session is interrupted and told to speak it, and the call ends `handoff` once it has finished or 10 s pass.
- **GL-09** — Given a Live call, when the session opens, then the greeting is spoken exactly once; and given the caller speaks during it, then no interruption happens, that audio is not forwarded and a turn recognised during it is not answered, until it finishes or 15 s pass.
- **GL-10** — Given the call ends for any reason (`end_call`, `farewell`, `handoff`, `idle`, `max_duration`, `hangup`, `error`), then the closing words finish first (at most 10 s), the browser receives `end` with that reason, the session is closed within 5 s, and the analysis job is queued once.
- **GL-11** — Given the model calls `look_at_camera`, when the camera is on, then the browser is sent one `frame_request`, the single JPEG it returns goes to the `evidence` module through `FrameSource`, and no frame is ever sent to the session; and given the camera is off, or no frame arrives within 3 s, then the look is declined without an observation.
- **GL-12** — Given the session cannot be opened or drops mid-call, then the call ends with reason `error`, the browser receives `end` with a reason, the transcript so far is kept, nothing waits longer than 10 s, and no second engine takes over.
- **GL-13** — Given an import of Google's generative AI SDK anywhere outside `adapters/liveagent/`, or a module that imports that adapter, when `arch_check` runs, then it fails; and given the `voice` module's relay, then it depends only on the `LiveAgent` port.
- **GL-14** — Given any API response, log line, call event or message to the browser produced during a Live call, then no credential, access token or private key appears in it.
- **GL-15** — Given the session reports usage, when the call ends, then the call's `tokens_in`, `tokens_out` and `llm_cost_usd` include it, priced from configuration; and given a model with no configured price, then the cost counts as zero and a warning is logged, not an error.
