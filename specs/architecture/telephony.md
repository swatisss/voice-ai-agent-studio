---
type: Component Spec
title: Telephony (Twilio phone channel)
description: Inbound phone calls through Twilio Media Streams - number-to-agent mapping, voice webhook and TwiML, the media-stream WebSocket, IVR context, transfer to a person, request security and settings.
status: stable
tags: [architecture, telephony, twilio, ivr]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Overview

A published agent can answer a real telephone call. The phone is another transport for the voice pipeline, not another brain: the audio arrives over a WebSocket from Twilio instead of from the browser, and everything after that is the same ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) for the cascade, [/architecture/realtime-voice.md](/architecture/realtime-voice.md) for the speech-to-speech option). Why Twilio Media Streams and not SIP: [/decisions/adr-0008-telephony-and-realtime-voice.md](/decisions/adr-0008-telephony-and-realtime-voice.md).

```
caller phone ─▶ (your IVR forwards here, optional) ─▶ Twilio number
                                                          │ 1. POST voice webhook  (signed)
                                                          ▼
                              /api/telephony/twilio/voice  ── looks up number → agent, creates the call,
                                                          │    answers TwiML <Connect><Stream url=wss://…/stream/{call_id}?token=…>
                                                          ▼ 2. WebSocket from Twilio (8 kHz mu-law frames, JSON events)
                              /api/telephony/twilio/stream/{call_id}  ── Pipecat + TwilioFrameSerializer
                                                          │ same pipeline, brain, tools, escalation as a browser call
                                                          ▼ 3. on hand-off: Twilio REST update → <Dial> transfer_to
```

Only inbound calls are supported. Outbound agents are still simulated in the browser ([/architecture/call-modes.md](/architecture/call-modes.md)).

# Phone numbers

A phone number belongs to one tenant and routes to one agent (its **published** version at call time). Table `phone_numbers` ([/data/data-model.md](/data/data-model.md)): `e164` (unique across all tenants), `agent_id`, `label`. Managed with `GET/POST/DELETE /api/phone-numbers` ([/api/rest-api.md](/api/rest-api.md)) and the CLI `uv run voiceai phone add <e164> --agent <name or id> [--label ...]`, `phone list`, `phone remove <e164>`.

* `e164` must match `^\+[1-9][0-9]{6,14}$`; a duplicate is 409 `number_in_use`; an unknown or other-tenant agent is 422.
* The number you buy in Twilio is configured in Twilio, not here; this table only says which agent answers it.
* This is the one place a request is routed to a tenant without a tenant header: the tenant is the row's `tenant_id` ([/architecture/multi-tenancy.md](/architecture/multi-tenancy.md)).

# Voice webhook — `POST /api/telephony/twilio/voice`

Twilio posts form fields including `CallSid`, `From`, `To`, `CallStatus`. Steps:

1. **Validate the signature** (below). Invalid → 403, no call.
2. Look up `To` in `phone_numbers`. Unknown number, an agent that is not published, or Twilio/OpenAI/Deepgram credentials missing for the agent's pipeline → answer TwiML `<Say>` "Sorry, this number is not in service." and `<Hangup/>`; no call row, no stream.
3. Create the call: `channel: voice`, `direction: inbound`, the agent's published version, `meta.telephony = {provider: "twilio", call_sid, from_last4, to}`. The full caller number is **not** stored (last four digits only). The call context is built from the IVR parameters (below).
4. Answer TwiML:

```xml
<Response>
  <Connect>
    <Stream url="wss://{PUBLIC_BASE_URL host}/api/telephony/twilio/stream/{call_id}?token={token}">
      <Parameter name="call_id" value="{call_id}"/>
    </Stream>
  </Connect>
  <Hangup/>
</Response>
```

`token` is an HMAC of `call_id` and an expiry (60 seconds) keyed with `TWILIO_AUTH_TOKEN`; it lets the stream endpoint trust that the webhook, not an arbitrary client, created the call.

# Media stream — `WS /api/telephony/twilio/stream/{call_id}?token=`

* Close codes: `4401` bad or expired token, `4404` unknown or ended call, `4500` voice unavailable (a required provider key is missing). A normal end closes with `1000`.
* Twilio sends JSON events: `connected`, `start` (carries `streamSid`, `callSid` and custom parameters), `media` (base64 mu-law, 8 kHz, 20 ms), `mark`, `stop`. The pipeline starts on `start`; the welcome ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), VO-07) is spoken as soon as it has. There is no `ready` message.
* Audio in: mu-law 8 kHz is decoded and resampled for the pipeline (16 kHz PCM for the cascade, 24 kHz for the realtime service). Audio out is converted back to mu-law 8 kHz in `media` events carrying the `streamSid`. Pipecat's stream resampler hands audio on in bursts of roughly 100 ms, which adds that much delay to the caller's side; native G.711 pass-through to the realtime service would remove it and is a possible later optimisation.
* **Barge-in**: when the caller interrupts, the serializer sends Twilio a `clear` event so queued audio is dropped (the browser equivalent is `{"type":"interrupt"}`).
* **End**: when the session ends for any reason ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md)) the server finishes the closing speech, then closes the socket; Twilio continues to `<Hangup/>` and the caller is disconnected. A Twilio `stop` event or a dropped socket ends the session with reason `hangup`.
* Phone calls have no end-of-call feedback prompt (there is no page); `call_feedback` is unaffected.

# IVR context

An IVR in front of the agent forwards the call to the Twilio number (or to a Twilio SIP URI) and can pass context. Webhook parameters named `ivr_<name>` (from the query string of the webhook URL or from the form body; for SIP, headers `X-IVR-<Name>`, which Twilio posts as `SipHeader_X-IVR-<Name>` — how each carrier surfaces them is confirmed in spike S4) become call context entries `ivr_<name>`.

* At most 10 entries; keys `^ivr_[a-z0-9_]{1,30}$`; values trimmed to 200 characters; anything else is dropped.
* The entries appear in the system prompt as `call_context` lines like any context ([/architecture/call-modes.md](/architecture/call-modes.md)). The IVR context **never** marks the caller verified: identity still needs `verify_member` ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)).
* Example: the IVR menu pressed "claims" → webhook `…/voice?ivr_menu=claims&ivr_lang=en` → the agent knows the caller chose claims.

# Transfer to a person

Agent config `telephony.transfer_to` ([/data/agent-config.md](/data/agent-config.md)) is an E.164 number or a `sip:` URI. When a phone call is escalated ([/architecture/escalation.md](/architecture/escalation.md)):

1. The hand-off (or safety) message is spoken in full as usual.
2. If `transfer_to` is set and Twilio REST credentials (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`) are configured, the platform updates the live call through the Twilio REST API with TwiML `<Dial>` to `transfer_to`. Twilio leaves the media stream and bridges the caller to that destination.
3. The call ends with reason `handoff` and the escalation stays `waiting` for the console exactly as today; the groundwork packet is for the person on the console. The transfer does not pass the packet to the destination's phone.
4. If `transfer_to` is unset, credentials are missing or the REST call fails, nothing else happens: the call ends with reason `handoff` and the caller hears the hand-off message and then the line closes (a `system` event records the failure). The failure is never retried and never changes the outcome.

A true warm transfer (the agent stays on the line, introduces the caller) is out of scope.

# Request security

* **Webhook signature (TEL-02).** Twilio signs each webhook with `X-Twilio-Signature`: Base64 HMAC-SHA1, keyed with the account's auth token, over the full URL Twilio called plus the sorted form fields. The platform computes the URL from `PUBLIC_BASE_URL` + the request path and query, compares in constant time and rejects mismatches with 403. A tunnel or proxy that changes the host makes every signature fail, so `PUBLIC_BASE_URL` must be exactly the URL configured in Twilio ([/build/runbook-phone.md](/build/runbook-phone.md)).
* **Stream token (TEL-04).** The stream endpoint accepts only a token minted by the webhook for that `call_id`, not expired, used once. Whether Twilio also signs the stream handshake is confirmed in spike S4; the token is the control this spec relies on.
* **Never disabled in the cloud (TEL-10).** `TWILIO_VALIDATE_SIGNATURE=0` is accepted only when the process is not on Cloud Run (`K_SERVICE` unset); on Cloud Run the app refuses to start the telephony routes with that setting.
* Secrets: `TWILIO_AUTH_TOKEN` and `TWILIO_ACCOUNT_SID` come from the environment or `apps/api/.env`, and on Cloud Run from Secret Manager. They are never logged, stored or returned by any endpoint.

# Settings

| Variable | Meaning |
|---|---|
| `PUBLIC_BASE_URL` | Public `https://` base of this service, for example the ngrok URL locally or the Cloud Run URL. Used in the stream URL (`wss://`) and for signature validation. |
| `TWILIO_AUTH_TOKEN` | Validates webhooks, mints stream tokens, authenticates REST calls. Required for the telephony routes. |
| `TWILIO_ACCOUNT_SID` | Only needed for transfer (REST). |
| `TWILIO_VALIDATE_SIGNATURE` | Default `1`. `0` is for local experiments only (TEL-10). |

`GET /healthz` reports `providers.twilio` (auth token configured, no network call) ([/architecture/deployment.md](/architecture/deployment.md)).

# Local verification

Two ways, both in [/build/runbook-phone.md](/build/runbook-phone.md):

1. **With Twilio**: a trial number, a tunnel (`ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`), `PUBLIC_BASE_URL` set to the tunnel URL, the number mapped with `voiceai phone add`, the number's webhook pointed at `${PUBLIC_BASE_URL}/api/telephony/twilio/voice`, then call the number from a real phone.
2. **Without Twilio**: `python scripts/fake_twilio.py --to <mapped number> --wav sample.wav` signs a webhook request, follows the TwiML to the stream URL and plays the WAV as mu-law `media` events, prints what the agent says back. It uses the same provider keys as a browser call and needs no account or tunnel.

# Acceptance

- **TEL-01** — Given a phone number mapped to a published agent and a correctly signed webhook request for it, when the webhook is called, then a voice call is created (direction `inbound`, the agent's published version, `meta.telephony.to` set, caller number stored as last four digits only) and the response is TwiML containing `<Connect><Stream>` with a `wss://` URL on `PUBLIC_BASE_URL`'s host that names the new call id and a token, followed by `<Hangup/>`.
- **TEL-02** — Given a webhook request with a missing or wrong `X-Twilio-Signature` (including a valid signature computed over a different URL), when it is posted, then the response is 403 and no call is created; given a valid signature, it is accepted.
- **TEL-03** — Given a dialled number that is unmapped, or mapped to an unpublished agent, or a pipeline whose provider key is missing, when the webhook is called, then the response is TwiML with a spoken "not in service" message and `<Hangup/>` and no call row exists.
- **TEL-04** — Given the stream endpoint, when a connection presents a missing, wrong, expired or already used token, then it closes with 4401 before any pipeline starts; given an unknown or ended call id it closes with 4404; given a valid token the pipeline starts on the Twilio `start` event.
- **TEL-05** — Given webhook parameters `ivr_menu=claims`, `ivr_lang=en` and a non-`ivr_` parameter `foo`, when the call is created, then the call context holds `ivr_menu` and `ivr_lang` only (at most 10 entries, values at most 200 characters), the system prompt's `call_context` lists them, and the call is still unverified.
- **TEL-06** — Given Twilio `media` events with mu-law audio, when the stream is running, then the pipeline receives the decoded audio, agent audio is sent back as mu-law `media` events carrying the `streamSid`, a Twilio `stop` event ends the session with reason `hangup`, and a caller interruption sends a `clear` event.
- **TEL-07** — Given an escalated phone call, when the hand-off message has been delivered and `telephony.transfer_to` is set with Twilio credentials, then one Twilio REST update with `<Dial>` to that destination is made and the call ends with reason `handoff`; given no `transfer_to`, or a failing REST call, then no transfer happens, the call still ends with reason `handoff`, and a failure leaves a `system` event.
- **TEL-08** — Given the phone-number API, when a number is added, listed and removed, then validation follows the rules above (E.164 format, 409 `number_in_use` on a duplicate, 422 for an unknown agent), a number of another tenant is not visible or removable (404), and removing it makes the webhook answer "not in service".
- **TEL-09** — Given a running API with a mapped number and `scripts/fake_twilio.py`, when it plays a WAV file against the mapped number, then the webhook returns TwiML, the stream is accepted, the call appears as `active` and then `ended` in the Calls list, and the agent's reply audio is received (checked by hand against a running server with provider keys).
- **TEL-10** — Given `TWILIO_VALIDATE_SIGNATURE=0`, when the process is on Cloud Run (`K_SERVICE` set), then the telephony routes refuse to start; when it is not, unsigned requests are accepted and a warning is logged; given no `TWILIO_AUTH_TOKEN`, the webhook answers the "not in service" TwiML and `/healthz` reports `providers.twilio: false`.
- **TEL-11** — Given a phone call that ends for any reason in [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), when the closing speech has finished, then the stream socket closes with 1000, `calls.end_reason` is that reason, and no feedback prompt is created for the call.
