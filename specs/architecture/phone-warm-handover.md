---
type: Component Spec
title: Phone warm handover
description: "A phone call escalated to a person becomes a Twilio conference: the caller waits, the specialist's phone or browser is rung and briefed, both are bridged and recorded on two channels, and after the call a batch transcription writes the human portion into the call's events for the learning loop."
status: draft
tags: [architecture, telephony, twilio, escalation, handover, recording, transcription]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Purpose

Today an escalated phone call is a cold `<Dial>` ([/architecture/telephony.md](/architecture/telephony.md), TEL-07): the caller is bridged to a number, the stream ends, nothing is recorded and the platform never learns what the person said. This spec adds a second **handover mode**, `conference`, for the owner's goal: a caller in India dials a Twilio US number, the AI answers, and on escalation a person in India (a mobile number, or the specialist's browser through the Twilio Voice SDK) takes the call **warm**: briefed first, recorded on two channels, transcribed afterwards into `human` events so the self-learning loop ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)) can learn from what the person actually said. Facts about Twilio's behaviour and the points still to be confirmed on a paid account are in the research note `.scratch/human-voice-and-channels/research/03-twilio-handover-whatsapp.md` (spikes S1 to S5).

"Warm" here means: the caller hears the hand-off message and then holds while the specialist's phone rings; the specialist hears a spoken brief of the call (from the groundwork packet) before being connected. The AI does **not** stay in the conference to introduce the two parties (out of scope).

# Agent settings

`telephony.handover` in the agent config ([/data/agent-config.md](/data/agent-config.md)), next to `transfer_to`:

```json
"telephony": { "transfer_to": "+919876500123",
               "handover": { "mode": "conference", "record": true, "ring_seconds": 30, "browser": false, "brief": true } }
```

| Field | Default | Rules |
|---|---|---|
| `mode` | `dial` | `dial` is today's cold transfer (TEL-07); `conference` is this spec. Anything else is 422. |
| `record` | `false` | Record the person-to-caller portion on two channels and transcribe it afterwards. |
| `ring_seconds` | `30` | How long the specialist's leg rings; integer 5 to 120. |
| `browser` | `false` | Also ring the browsers of specialists who are **Ready** in Agent Desk (below). First to answer wins. |
| `brief` | `true` | Speak a short brief of the call to the specialist before connecting (`conference` mode only). |

`mode: conference` needs a destination: `transfer_to` must be an E.164 number (a `sip:` URI is not accepted for a conference leg) or `browser` must be `true`; otherwise saving is 422 `handover_needs_destination`. An agent without `handover` behaves exactly as before.

# Flow (mode `conference`)

Triggered where TEL-07 is today: the escalation's hand-off (or safety) message has been spoken in full ([/architecture/escalation.md](/architecture/escalation.md), step 6) and Twilio REST credentials are configured. The adapter's `transfer` seam ([/architecture/telephony.md](/architecture/telephony.md), Carrier adapters) takes the call reference and a handover plan instead of a bare destination.

1. **Name the conference** `h-{call_id}` and record `calls.meta.handover = {mode: "conference", state: "pending", conference: name, caller_sid, started_at}`; a `system` event `handover_started` is added.
2. **Move the caller.** One REST update of the caller's live call with TwiML (Twilio runs it in place of the stream, which ends; the server closes the socket with 1000 and the `stop` event is not a hang-up because the call is already ending `handoff`):

```xml
<Response>
  <Say>This call may be recorded for quality and training.</Say>   <!-- only when record is true (TEL-26) -->
  <Dial>
    <Conference startConferenceOnEnter="false" endConferenceOnExit="true" beep="false"
                waitUrl="" participantLabel="caller" record="record-from-start"
                recordingStatusCallback="{PUBLIC_BASE_URL}/api/telephony/twilio/handover/recording/{call_id}"
                recordingStatusCallbackEvent="completed"
                statusCallback="{PUBLIC_BASE_URL}/api/telephony/twilio/handover/conference/{call_id}"
                statusCallbackEvent="start end join leave">h-{call_id}</Conference>
  </Dial>
</Response>
```

   The caller is first in the conference and is muted and hears the wait audio (`waitUrl` is an empty string for silence by default; the `TWILIO_HOLD_URL` setting plays an MP3 instead). The `record` and recording attributes are omitted when `record` is false. If the update fails, nothing more happens (as TEL-07 step 4): the call ends `handoff`, a `system` event records `handover_failed`.
3. **Ring the specialist.** One `Calls.create` per leg, created after step 2: To the `transfer_to` number (`From` is `TWILIO_FROM_NUMBER`, else the number the caller dialled, so it is always a non-Indian Twilio number), `Timeout` = `ring_seconds`, `StatusCallback` to `…/handover/specialist/{call_id}`, and inline TwiML:

```xml
<Response>
  <Say>{brief}</Say>                                              <!-- omitted when brief is false -->
  <Dial><Conference startConferenceOnEnter="true" endConferenceOnExit="false" beep="false"
          participantLabel="specialist">h-{call_id}</Conference></Dial>
</Response>
```

   With `browser: true`, one more leg per Ready specialist is created in the same way with To `client:{identity}` (whether `Calls.create` accepts a `client:` destination is spike S4; the fallback is a `<Dial><Client>` TwiML route). The legs ring in parallel; the first to answer wins and every other leg is updated with `Status=canceled`.
4. **Connect.** When the specialist's leg joins, the conference starts and the two are bridged; `calls.meta.handover.state` becomes `connected` (`answered_by: phone|browser`) and a `system` event `handover_connected` is added. A **browser** answer also accepts the escalation for that specialist (the same rules as `POST /api/escalations/{id}/accept`, a no-op unless it is `waiting`); a **phone** answer leaves the escalation `waiting` for the console, as TEL-07 does, because a number is not a signed-in person.
5. **End.** The conference ends when the caller leaves (`endConferenceOnExit` on the caller) or the specialist's leg ends; the state becomes `ended` and a `system` event `handover_ended` records the length. The specialist still resolves the escalation in the console with a note ([/architecture/escalation.md](/architecture/escalation.md)).

**No answer.** If every leg ends `no-answer`, `busy`, `failed` or `canceled` before anyone joined, the caller (still waiting in the conference) is updated with TwiML that says "I'm sorry, nobody is available right now. We have your request and a colleague will call you back." and hangs up; state `no_answer` or `failed`, `system` event `handover_failed` with the Twilio status, the escalation stays `waiting`. Never retried, never changes the call's end reason (`handoff`). A return to the AI is out of scope.

**Mode `dial` with `record: true`** keeps TEL-07's TwiML and adds `record="record-from-answer-dual"` with the same recording callback (caller on channel 1, specialist on channel 2); it has no brief, no hold and no join events, and the channel map is fixed `{1: caller, 2: specialist}`.

# The brief

Spoken to the specialist, from the groundwork packet when `packet_status` is `ready` or `fallback`: "Caller for {intent words}. {summary}. Suggested next step: {suggested_next_action}." No more than 300 characters, passed through `mask.text()` ([/architecture/agent-desk.md](/architecture/agent-desk.md)) so no member reference, email address or telephone number is read out, and XML-escaped. If the packet is still `pending`, the brief is "A caller needs a person. The details are on your Agent Desk." The full packet stays on the console.

# Callbacks

All three are signed ([/architecture/telephony.md](/architecture/telephony.md), TEL-02, TEL-10), answer 200 with an empty body, are idempotent, and answer 404 for a `call_id` without `calls.meta.handover`.

| Route | Twilio fields used | Effect |
|---|---|---|
| `POST /api/telephony/twilio/handover/specialist/{call_id}` | `CallSid`, `CallStatus` | tracks each leg; a leg ending without a join counts toward `no_answer`; when one leg answers the others are cancelled |
| `POST /api/telephony/twilio/handover/conference/{call_id}` | `ConferenceSid`, `StatusCallbackEvent`, `CallSid`, `ParticipantLabel` | `join` of the `specialist` label connects (step 4) and stores the **join order**; `end` ends the handover |
| `POST /api/telephony/twilio/handover/recording/{call_id}` | `RecordingSid`, `RecordingUrl`, `RecordingStatus`, `RecordingDuration`, `RecordingChannels`, `CallSid` | stores a recording row (below) |

Event and field names for the first two are checked in spikes S4, S5 and S9; the recording fields are as documented by Twilio.

# Recording and transcription

* **Row.** A completed recording creates a `call_recordings` row ([/data/data-model.md](/data/data-model.md), DM-21): `recording_sid` (unique, the idempotency key), `source` (`conference`|`dial`), `channels` (from `RecordingChannels`), `duration_s`, `channel_map` and `status` `received`; it queues one `transcribe_handover` job ([/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)). `channel_map` is `{"1": "caller", "2": "specialist"}` when the caller joined the conference first (the normal order, step 2 before 3); if the stored join order says otherwise it is inverted; for `channels: 1` there is no map (mixed). **No audio is stored in the database**: the job streams the media into memory, transcribes it and discards it.
* **Dual-channel conference recording is a Twilio account setting** ("Dual-channel Recording for Conference"; first participant on channel 1, everyone else mixed on channel 2). With it off, conference media is mono; the job requests `RequestedChannels=2` and on a 400 retries with 1.
* **Fetching.** The media URL is read with HTTP Basic using `TWILIO_API_KEY_SID` and `TWILIO_API_KEY_SECRET`; `.wav` is requested.
* **Transcriber.** A small interface in the voice package, `Transcriber.transcribe(wav_mono: bytes, languages: list[str]) -> list[Segment(start_s, end_s, text, language)]`, with two provider settings: `HANDOVER_STT_PROVIDER` (default `deepgram`, pre-recorded API with the existing `DEEPGRAM_API_KEY`, one request per channel so the speakers stay apart) and `HANDOVER_STT_LANGUAGE` (default `auto`, else a language code). A second implementation for Sarvam (Indian languages including code-mixed Hindi and English; its REST endpoint takes short audio, so it chunks each channel by silence) is **an option behind the same interface, not part of this change**: a new vendor needs its own ADR first (data residency, key handling, cost). The agent's `languages` are passed as hints.
* **Events.** The job appends to the call's events after its last `seq`, ordered by time, with `at` = recording start + `start_s`: the caller channel becomes `user` events and the specialist channel `human` events (kind added by CP-0049, `/architecture/human-message-channel.md`, DM-17); both carry `data: {on_human_leg: true, start_s, end_s, language}`, and `human` carries `author` (the assignee's name, else "Specialist"). A mono recording writes `human` events with `data.speaker: "mixed"` and a `system` event `recording_mono`. The row becomes `transcribed`; `handover.transcribed` `{call_id, recording_id}` is published on topic `console`. Running the job again for the same recording adds nothing.
* **Failure.** A failed download or transcription follows the job queue's retry rules; at the end the row is `failed` with `error`, no events are written, and the call, escalation and learning are untouched. Provider keys never appear in logs or rows.
* **Retention.** After a successful transcription the Twilio recording is deleted through Twilio's Recordings API when `TWILIO_RECORDING_DELETE=1` (default `1`; the delete call is confirmed in spike S3) and the row becomes `deleted`. The transcript, not the audio, is what the platform keeps.

# Learning loop

The `human` events with `on_human_leg` are what a person told the caller, the same ground truth as the resolution note.

* The job re-queues `analyze_call` for the call with the existing re-analysis key `analyze_call:{call_id}:2` ([/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)), and `score_call:{call_id}:2` follows, so the analysis sees the human portion.
* The fix drafter's evidence for a member call carries one line "Human portion (specialist): …", the specialist's lines joined and cut at 600 characters, in addition to the resolution note ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)).
* Call scoring ([/architecture/call-scoring.md](/architecture/call-scoring.md)) judges the **AI's** turns only: `user` and `assistant` events without `on_human_leg`; a transcribed handover does not change the scorecard.

# Agent Desk: the specialist's browser as a phone

* `POST /api/desk/phone-token` (specialist, admin, reviewer) returns `{token, identity, ttl_seconds}`: a Twilio Access Token with the Voice grant, `incoming` allowed, signed with `TWILIO_API_KEY_SID`/`TWILIO_API_KEY_SECRET`, for `identity` = `desk-{user id}`; 503 `phone_unavailable` when those are not set. The token is short-lived (default 3,600 s) and never logged.
* `PUT /api/desk/phone-presence {ready: bool}` marks the specialist **Ready**; the page repeats it every 30 seconds while the control is on, and a presence older than 90 seconds counts as not ready (table `desk_presence`, DM-21). Only Ready specialists of the call's business unit are rung when `browser` is true.
* The page ([/ui/agent-desk.md](/ui/agent-desk.md), UI-91 to UI-93) registers a Twilio `Device` with that token, shows the incoming call with the packet, and answers, mutes and hangs up.
* Both calls are in the specialist's allow-list ([/architecture/agent-desk.md](/architecture/agent-desk.md), DESK-12).

# Privacy, consent and India

* Caller and specialist numbers are never stored in full (last four digits only, as before); the conference name carries the call id only.
* **Recording consent.** Twilio warns that recording may need consent. With `record: true` the caller hears the notice in step 2 (text from `TWILIO_RECORDING_NOTICE`, default "This call may be recorded for quality and training.") and the specialist sees "Recorded" ([/ui/agent-desk.md](/ui/agent-desk.md), UI-92); the legal position for India is **not verified** and is an owner decision before real people are called.
* **Calling an Indian number from Twilio** requires a non-Indian Twilio caller ID and the account's voice geographic permissions to allow India; Twilio treats commercial calls without the recipient's consent as unsolicited under TRAI rules and may block them. The specialist is an employee who has agreed to take handover calls; the platform never dials a member this way. See the runbook ([/build/runbook-twilio-handover-whatsapp.md](/build/runbook-twilio-handover-whatsapp.md)).
* Synthetic data only in demos and tests.

# Settings

| Variable | Meaning |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `PUBLIC_BASE_URL`, `TWILIO_FROM_NUMBER` | As in [/architecture/telephony.md](/architecture/telephony.md); `TWILIO_FROM_NUMBER` must be a non-Indian Twilio number for Indian destinations. |
| `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` | Download recordings; sign browser tokens. Handover without them still connects; recordings are then not transcribed (a `system` event says why) and the browser leg is off. |
| `TWILIO_HOLD_URL` | Optional MP3 played to the waiting caller; empty = silence. |
| `TWILIO_RECORDING_NOTICE` | Spoken to the caller when recording. |
| `TWILIO_RECORDING_DELETE` | `1` (default) deletes the Twilio recording after a successful transcription. |
| `HANDOVER_STT_PROVIDER`, `HANDOVER_STT_LANGUAGE` | Transcriber provider (`deepgram`) and language (`auto`). |

`GET /healthz` adds `providers.twilio_voice_sdk` (API key configured, no network call).

# Acceptance

- **TEL-14** — Given an agent config with `telephony.handover` `{mode: "conference", record: true, ring_seconds: 30, browser: false, brief: true}` and `transfer_to: "+919876500123"`, when it is saved, then it is accepted; `mode: "teams"`, `ring_seconds: 3` or `200`, a non-boolean `record`, and `mode: "conference"` with neither an E.164 `transfer_to` nor `browser: true` (including a `sip:` `transfer_to`) are each 422 (`handover_needs_destination` for the last); an agent without `handover` keeps `mode: dial`.
- **TEL-15** — Given an escalated phone call of an agent in `conference` mode with Twilio credentials, when the hand-off message has been delivered, then exactly one Twilio call update puts the caller in conference `h-{call_id}` with `startConferenceOnEnter="false"`, `endConferenceOnExit="true"`, label `caller` and the status callbacks on `PUBLIC_BASE_URL`, then exactly one call is created to `transfer_to` from a non-Indian Twilio number with `Timeout` `ring_seconds` and TwiML that joins the same conference with `startConferenceOnEnter="true"` and label `specialist`; the call ends `handoff`, `meta.handover.state` is `pending` then `ringing` and a `handover_started` system event exists; an update that fails creates no specialist call and leaves a `handover_failed` event.
- **TEL-16** — Given `mode: dial` (or no `handover`), then the TwiML is TEL-07's unchanged and no recording attribute is present; given `mode: dial` and `record: true`, then the `<Dial>` has `record="record-from-answer-dual"` and a recording status callback to the handover recording route.
- **TEL-17** — Given a handover in `ringing`, when the conference callback reports a `join` with label `specialist` from a phone leg, then the state is `connected` with `answered_by: phone`, a `handover_connected` event exists and the escalation is still `waiting`; given the join came from a browser leg of a Ready specialist, then the escalation is `accepted` with that specialist as assignee.
- **TEL-18** — Given a handover whose specialist leg reports `no-answer` (and again `busy` and `failed`), then the caller's call is updated with TwiML that speaks the call-back apology and hangs up, `meta.handover.state` is `no_answer` (or `failed`), a `handover_failed` event carries the status, the escalation is `waiting`, nothing is retried and the call's end reason is still `handoff`; given two legs (phone and browser), the first to join wins and the other leg is updated with `Status=canceled`.
- **TEL-19** — Given a packet whose summary contains "member NGH-410237, email meera@example.com, phone 07700900123" and is 600 characters long, when the brief is built, then it is at most 300 characters, contains none of the three identifiers in full and no XML-breaking character; given `packet_status: pending` it is the generic line; given `brief: false` the specialist TwiML has no `<Say>`.
- **TEL-20** — Given the three handover callback routes, when a request has a missing or wrong signature, then 403 and nothing changes; for a `call_id` without `meta.handover` 404; a repeated identical callback changes nothing (one join, one `handover_connected` event).
- **TEL-21** — Given a recording callback with `RecordingStatus: completed`, `RecordingChannels: 2` and a conference whose stored join order is caller first, then one `call_recordings` row exists with `channel_map {"1":"caller","2":"specialist"}`, status `received`, and one `transcribe_handover` job is queued; the same `RecordingSid` again adds neither a row nor a job; `in-progress` and `absent` are recorded without a job.
- **TEL-22** — Given a fake Transcriber and a two-channel fixture recording, when `transcribe_handover` runs, then the call's events gain, after its last `seq`, `user` events (caller channel) and `human` events (specialist channel with the assignee's name) ordered by time, all with `on_human_leg: true`, the row is `transcribed` and `deleted` after the delete call, and `handover.transcribed` is published; given a mono recording the segments are `human` events with `speaker: "mixed"` plus a `recording_mono` system event; running the job twice writes the events once; the 400 on `RequestedChannels=2` is retried with 1.
- **TEL-23** — Given a recording whose download or transcription fails every attempt, then the row is `failed` with an error, no events are written, the call and escalation are unchanged, and no key appears in logs; given no `TWILIO_API_KEY_SID`, a `system` event says recordings are not transcribed and no job is queued.
- **TEL-24** — Given a call with transcribed `human` events, then the transcription job re-queues `analyze_call` once for it, the fix drafter's evidence contains "Human portion (specialist): …" cut at 600 characters, and the call's scorecard counts only events without `on_human_leg`.
- **TEL-25** — Given a signed-in specialist, when they call `POST /api/desk/phone-token` with the API key configured, then the answer has a token, identity `desk-{id}` and `ttl_seconds`, no secret; unconfigured it is 503 `phone_unavailable`; `PUT /api/desk/phone-presence {ready: true}` makes them Ready for 90 seconds and `{ready: false}` or silence ends it; a Ready specialist of another business unit is not rung.
- **TEL-26** — Given `record: true`, then the caller's conference TwiML starts with `<Say>` of `TWILIO_RECORDING_NOTICE` and the conference has `record="record-from-start"`; given `record: false` there is neither the notice nor any recording attribute.
- **TEL-27** — Given a paid Twilio account, a US number mapped to a front desk, an Indian mobile as caller and a second Indian mobile as `transfer_to`, when the caller asks for a person, then the second phone rings, the brief is spoken, the two are bridged, the recording completes on two channels and the call's events show the human portion (checked by hand against a running server; spikes S1 to S5 of the research note pass).
