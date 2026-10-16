---
type: Tool Spec
title: Twilio simulator
description: scripts/twilio_sim.py - a local stand-in for Twilio with a browser phone, so inbound and outbound phone calls run through the real platform path with no Twilio account.
status: stable
tags: [build, tooling, telephony, simulator, demo]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# What it is

A small server (default `http://localhost:9200`) that plays Twilio's part towards the platform ([/architecture/telephony.md](/architecture/telephony.md)) and gives the presenter a **phone in the browser**. The platform code is unchanged: it talks to the simulator through the same settings it uses for Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_API_BASE`, `PUBLIC_BASE_URL`). To go to real Twilio later: remove `TWILIO_API_BASE`, use your real credentials and number.

Do not confuse it with `scripts/fake_twilio.py`, which replays one recorded WAV file into a running platform and exits ([/build/runbook-phone.md](/build/runbook-phone.md)); the simulator is interactive and also takes the platform's own REST calls.

# Usage

```bash
python scripts/phone_demo.py --simulator     # recommended: starts the simulator and the API wired together
cd apps/api && uv run python ../scripts/twilio_sim.py   # the simulator alone (the API must be running)
```

| Setting | Default | Meaning |
|---|---|---|
| `SIM_PORT` | `9200` | where the simulator and its browser phone listen |
| `SIM_PLATFORM_URL` | `http://127.0.0.1:8000` | where the platform listens (its webhook and stream) |
| `PUBLIC_BASE_URL` | the platform URL | the URL the platform believes Twilio calls; signatures are computed over it |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | `ACsimulator`, `simulator-token` | must equal the platform's values |
| `TWILIO_PHONE_NUMBER` | `+15550001111` | the platform's phone number (the number the browser phone dials; the caller ID of outbound calls) |

# The browser phone

* **Dial pad.** The number field starts with the platform's number; **Call** places an inbound call: the simulator posts the signed voice webhook, follows the TwiML to the Media Stream and bridges your microphone and speaker to it. **End** hangs up.
* **Outbound.** A panel lists the outbound agents and their targets (from the platform) and a field "your phone number"; **Call me** asks the platform to place an outbound call to that number ([/architecture/telephony.md](/architecture/telephony.md), TEL-12). The page then shows an **incoming call** banner with **Answer** and **Decline**; Answer connects the call (the agent speaks the persona opening), Decline refuses it.
* **Status line** shows ringing, connected (with duration), "transferred to +…" after a hand-off redirect, ended.
* The conversation itself (transcript, tool calls, escalation, cost) is on the platform's Calls page.

# What it simulates

| Twilio behaviour | Simulator |
|---|---|
| `GET /2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json?PhoneNumber=` and `POST …/IncomingPhoneNumbers/{PN}.json` (`VoiceUrl`, `VoiceMethod`) | one number (`TWILIO_PHONE_NUMBER`) whose voice URL is stored; `scripts/phone_demo.py` and the platform use them unchanged |
| `POST …/Calls.json` (`To`, `From`, `Twiml` or `Url`) | creates an outgoing call that rings in the browser phone; the answer connects to the `<Stream url>` of the TwiML |
| `POST …/Calls/{sid}.json` with `Twiml` containing `<Dial>` (the platform's hand-off) | the stream is closed, the phone shows "transferred to …" |
| `POST …/Calls/{sid}.json` with `Status=completed` | the call is hung up |
| Voice webhook, TwiML, Media Stream | signs the webhook like Twilio (HMAC-SHA1 over the public URL and form fields), reads the TwiML, opens the stream and sends `connected`, `start` (`streamSid`, `callSid`, custom parameters), `media` (mu-law 8 kHz, 20 ms), `stop`; understands the platform's `media`, `clear` and `mark` |

It does not simulate Twilio's trial notice, carrier audio quality, billing, SMS, or status callbacks.

# Acceptance

- **SIM-01** — Given the simulator, when the number's webhook is read and set through `IncomingPhoneNumbers` (the calls `scripts/phone_demo.py` makes), then the listing returns the simulator's number with its current voice URL, the update stores the new voice URL and method, an unknown number lists nothing, and wrong credentials are refused with 401.
- **SIM-02** — Given a platform that answers the webhook with TwiML, when a call is dialled from the browser phone, then the simulator posts a form signed with the auth token over `PUBLIC_BASE_URL` + the webhook path, connects to the stream URL in the TwiML (on the platform's host), sends `connected` then `start` with a `streamSid`, a `callSid` and the TwiML's custom parameters, and ends the call with a `stop` event when the phone hangs up.
- **SIM-03** — Given a call is bridged, then 8 kHz 16-bit audio from the phone reaches the stream as mu-law `media` events of 20 ms, `media` from the platform reaches the phone as 8 kHz 16-bit audio, and a `clear` event makes the phone drop its queued playback.
- **SIM-04** — Given `Calls.json` is posted with a `Twiml` carrying a `<Stream>`, then the call is listed as ringing with its `To` and `From`; Answer connects it as in SIM-02 (the TwiML's stream URL is used as given, the call's `From` is the platform's number); Decline marks it `no-answer`, closes nothing on the platform and frees the phone; an unanswered call stops ringing after the ring timeout.
- **SIM-05** — Given a connected call, when `Calls/{sid}.json` is posted with `<Dial>` TwiML, then the simulator closes the stream and reports "transferred to" that destination; with `Status=completed` it hangs the call up; a platform that closes the stream ends the call on the phone.
- **SIM-06** — Given `python scripts/phone_demo.py --simulator`, when the browser phone dials the number and the presenter speaks, then the Insurance Claims Agent answers and the call appears on the Calls page with the Phone badge; an outbound call placed from the phone page rings, and Answer starts the agent's opening (by hand).
