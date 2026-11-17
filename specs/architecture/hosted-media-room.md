---
type: Component Spec
title: Hosted media room and live voice handover
description: A voice call in a LiveKit Cloud room - the browser customer and the AI share the room, a specialist on another machine takes the call (the AI leaves), and a scribe turns both human voices into call events for the learning loop.
status: stable
tags: [architecture, voice, livekit, handover, escalation, agent-desk]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Purpose

Today the AI call ends when a call is escalated ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), CE-01) and Agent Desk has no audio ([/architecture/agent-desk.md](/architecture/agent-desk.md)). This spec adds a third voice transport, `livekit`, in which the call lives in a **room** on LiveKit Cloud ([ADR-0015](/decisions/adr-0015-hosted-media-room-livekit.md)): the customer talks to the AI from the browser; on escalation a specialist signed in to Agent Desk takes the voice call from another machine; both human legs are transcribed so the specialist's words feed self-learning. Research and sources: `.scratch/human-voice-and-channels/research/02-livekit-cloud.md`. The text counterpart (a human typing into a call) is the human message channel of CP-0049; this spec reuses its `human` call-event kind and does not redefine it.

It is a transport and a hand-over, not a new pipeline: the AI's brain (cascade by default, [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md); turn policy, tools, escalation, scoring) is unchanged.

# Participants

| Identity (opaque, no personal data) | Who | Runs where | Token grants |
|---|---|---|---|
| `cust-<random>` | The customer in the browser (Test call page, later the public API) | browser, `livekit-client` | join one room; publish microphone only; subscribe; **no data publish** |
| `ai-<call_id>` | The AI agent (Pipecat `LiveKitTransport`, [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md)) | our API process (outbound only) | join; publish audio; subscribe; data publish |
| `spec-<random>` | The specialist in Agent Desk | browser | join; publish microphone; subscribe; data publish; **no `roomAdmin`** |
| `scribe-<call_id>` | The scribe: subscribes to each human track and transcribes it | our API process | join; **subscribe only** (no publish) |

The room name is `lk-<call_id>`. Tokens are minted by the API with `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`, live at most `LIVEKIT_TOKEN_TTL_S` (default 600), and are returned once; the secret is never returned or logged. The server's own key can remove a participant and close a room; no browser token can.

# Flow

1. **Start.** `POST /api/calls {channel: "voice", transport: "livekit"}` ([/api/rest-api.md](/api/rest-api.md)) runs [call admission](/architecture/call-admission.md) and returns `connect: {url, token, room, expires_at}`. The browser connects and publishes the microphone; the API process starts the AI participant, which speaks the welcome first as on every voice call.
2. **Conversation.** The AI hears only the customer: frames of any other identity are not passed to the turn policy (the specialist never reaches the model). Transcript events come from the same pipeline as other voice calls, so the call page, scoring and analysis are unchanged.
3. **Escalation.** On any trigger ([/architecture/escalation.md](/architecture/escalation.md)) the hand-off message is spoken as today and the escalation is created. Because the call is in a room, **the call stays open**: status `escalated`, `escalations.voice_state: waiting`, the AI stops answering (no model request on customer speech), the browser receives the control message `handover {state: "waiting"}` and the console event carries `voice: "waiting"`. The customer hears nothing until the specialist joins. A clock `HANDOVER_WAIT_S` (default 180) runs while `voice_state` is `waiting`.
4. **Take the call.** In Agent Desk the specialist clicks **Take the call** (`POST /api/escalations/{id}/voice/join`): the escalation becomes `accepted` (assignee is the signed-in name), `voice_state` stays `waiting` until they connect, and the response is `{url, token, room, expires_at}`. A second specialist gets 409.
5. **Warm hand-over.** When `spec-*` connects, the AI says one introduction line (the packet's `summary` is on the specialist's screen; the line is a fixed sentence naming the specialist: "I'm bringing in Sam, who has the details of your request."), then its participant disconnects and the AI segment ends with reason `handoff`. `voice_state` becomes `connected`, `handover {state: "connected", specialist: "Sam"}` goes to the customer. Customer and specialist hear each other (every track is auto-subscribed). The AI does not rejoin.
6. **Scribe.** At step 5 (or at escalation, so the specialist's first words are not lost) the scribe joins and transcribes **each remote audio track separately** with the call's STT provider. The customer's finals continue as `user` events; the specialist's finals are `human` events (`{role: "specialist", source: "voice", text, participant}`), with `seq` shared with all other events. Audio is not stored. Partial results appear as `call.partial`.
7. **End.** The call ends by the first of: the specialist presses **Resolve** (call ends `human_ended`, the room is closed, the customer receives `end`), the customer disconnects (`hangup`; the escalation stays `accepted` so the specialist can still resolve), `HANDOVER_WAIT_S` elapsing with no specialist connected (`handover_timeout`), or `policy.max_call_seconds` (`max_duration`). If the specialist drops while the customer stays, `voice_state` returns to `waiting`, the clock restarts and the customer sees "Your specialist was disconnected, please hold"; no AI rejoins.
8. **Learning.** After the call, analysis and clustering see the specialist's spoken lines as human turns ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)); the resolution note remains required and remains the strongest evidence.

# Control messages

Server to browsers over room data packets, topic `echo.control`, JSON `{type, ...}` ([/api/voice-protocol.md](/api/voice-protocol.md) names the WebSocket equivalents): `ready`, `handover {state: "waiting"|"connected"|"waiting_again", specialist?}`, `end {reason}`. Browsers send none: ending is disconnecting. The specialist page may send `{type: "mute"}` only as UI state; nothing depends on it.

# Failure and limits

* **No configuration.** Without `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`, `transport: livekit` returns 503 `livekit_unavailable`; `/healthz` reports `livekit: false`. Every other transport behaves as before.
* **Cascade only.** A room call runs the cascade pipeline; an agent set to the realtime pipeline is refused with 409 `livekit_cascade_only` until the check proves a realtime room pipeline.
* **The AI cannot join** within 10 s: the call ends with reason `error`, the customer sees "Voice is unavailable", nothing is billed beyond the failed attempt.
* **Free plan caps are hard** (5,000 participant-minutes, 100 concurrent connections, 5 concurrent agent sessions; research note): when LiveKit refuses a join, the same `error` ending applies. A staffed call is up to four participants.
* **Cloud Run.** The AI and scribe are outbound clients inside the one service (min and max instances 1, no CPU throttling, [/architecture/deployment.md](/architecture/deployment.md)). Whether UDP media leaves Cloud Run is **UNVERIFIED**; `scripts/livekit_check.py` (LKH-16) decides, and the fallback in the ADR is a separate always-on worker.
* **Privacy.** The specialist hears the customer's real voice; transcripts of human turns are stored like all call events and masked for specialists as in [/architecture/agent-desk.md](/architecture/agent-desk.md). Recording audio is out of scope.

# Acceptance

- **LKH-01** — Given the three LiveKit settings, when `POST /api/calls` is sent with `channel: "voice", transport: "livekit"`, then the response has `connect.url`, a `connect.token` that decodes to the room `lk-<call_id>` and `connect.room`; without a setting it is 503 `livekit_unavailable` and `/healthz` has `livekit: false`; the other transports are unchanged.
- **LKH-02** — Given a customer token, then it grants join to its one room, microphone publishing, subscribing, no data publishing, no admin, an identity `cust-` plus a random suffix without personal data, a lifetime of at most `LIVEKIT_TOKEN_TTL_S`, and the API secret appears in no response, event or log line.
- **LKH-03** — Given a connected customer, then the AI participant joins, speaks the welcome first, answers by the same turn policy as other voice calls and hears only the customer: audio of any other identity never reaches the model.
- **LKH-04** — Given the customer disconnects, then the call ends with reason `hangup` within 5 s, `ended` is published, and an open escalation stays `accepted` or `waiting` for the console.
- **LKH-05** — Given a call in a room that escalates, then after the hand-off message the call stays `escalated`, `voice_state` is `waiting`, the browser receives `handover {state: "waiting"}`, the console event carries `voice: "waiting"`, and a customer utterance causes no model request.
- **LKH-06** — Given `voice_state: waiting` for `HANDOVER_WAIT_S` with no specialist connected, then the call ends `handover_timeout`, the browser receives `end`, and the escalation stays `waiting` for a callback.
- **LKH-07** — Given `POST /api/escalations/{id}/voice/join`, then for a specialist of the same business unit and a `waiting` voice escalation it accepts the escalation and returns a specialist token (publish, subscribe, data, no admin); a non-voice or non-waiting escalation is 409, another unit 403 `tenant_forbidden`, a call without LiveKit configured 503.
- **LKH-08** — Given a connected specialist, then the AI says exactly one introduction line, disconnects within 10 s, its segment ends `handoff`, `voice_state` is `connected`, the customer receives `handover {state: "connected"}`, and the AI produces no audio afterwards.
- **LKH-09** — Given customer and specialist speaking, then the customer's finals are `user` events and the specialist's are `human` events with `source: "voice"`, in one `seq` order, and no audio is stored.
- **LKH-10** — Given a call with spoken human turns that has been resolved, then analysis input and cluster evidence include the specialist's lines as human turns and the resolution note is still required (ES-07).
- **LKH-11** — Given **Resolve** while connected, then the call ends `human_ended`, the room is closed, the customer receives `end {reason: "human_ended"}`, and the call's outcome is `escalated`.
- **LKH-12** — Given the specialist disconnects while the customer stays, then `voice_state` returns to `waiting`, the customer receives `handover {state: "waiting_again"}`, the clock restarts, and no AI participant rejoins.
- **LKH-13** — Given the AI participant cannot join within 10 s or LiveKit refuses the join, then the call ends `error` and the browser receives a failure it can show ("Voice is unavailable").
- **LKH-14** — Given unit tests, then they use a fake room: no network, no LiveKit account, no secret.
- **LKH-15** — Given the specialist role, then `POST /api/escalations/{id}/voice/join` and `GET /api/escalations/{id}/voice` are on its allow-list and no other new request is.
- **LKH-16** — Given `python scripts/livekit_check.py` with the three settings, then it mints a token, joins a throw-away room as a participant, reports signalling OK, media path (UDP, TCP or relay) and round-trip time, never prints the secret or token, and exits non-zero on failure.
