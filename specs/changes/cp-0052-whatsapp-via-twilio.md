---
type: Change Proposal
title: CP-0052 WhatsApp via Twilio as a text channel with human handover
description: WhatsApp (Twilio sandbox first, a production sender later) talks to the same agents, escalates to Agent Desk over the human message channel, respects the 24-hour window with a template for late replies, handles opt-out and Hindi voice notes, and keeps the user's address out of everything but one column.
status: stable
cp_state: accepted
tags: [whatsapp, twilio, channels, escalation, privacy]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The owner (Phase 3) wants WhatsApp on Twilio as a text channel into the platform with a human handover through Agent Desk. CP-0049 designs the human message channel once, for text from the public API; WhatsApp is the first other channel to use it. Research (`.scratch/human-voice-and-channels/research/03-twilio-handover-whatsapp.md`, 2026-11-16) found from Twilio's docs: the inbound webhook is SMS-shaped and signed like voice; free-form replies are allowed only within 24 hours of the user's last message and otherwise need an approved template sent through the Content API; the sandbox is a shared number with a 3-day join, one message per 3 seconds and no custom templates; a production sender needs a Meta business portfolio and verification (weeks).

# What changes

* **Channel.** `POST /api/channels/twilio/whatsapp/inbound` (signed, answers immediately, replies by REST) and `.../status` for delivery receipts. A `whatsapp_senders` table maps a sender address (sandbox `whatsapp:+14155238886` or a production number) to an agent or the front desk; a `whatsapp_threads` table keys a user to an open conversation (`source: whatsapp`, `channel: text`) and holds the window clock.
* **AI turns** use the existing text turn, safety screen and request-for-a-person rule; first reply carries the virtual-assistant disclosure; replies are plain text, split at 1,500 characters; sandbox sends are paced.
* **Human handover** reuses CP-0049: customer lines stored `to_human`, specialist replies through `POST /api/escalations/{id}/messages` (now also allowed for WhatsApp conversations), `escalation.message` console events. A delivery adapter sends each reply free-form inside the window; **outside it** the reply is queued and an approved follow-up template is sent, the queued text going out when the customer replies (production only; the sandbox answers 409 `window_closed`).
* **Window, delivery state and opt-out** are visible to the specialist (`channel_state`, per-message delivery, countdown); `STOP` opts out; resolve sends one closing message and a later message opens a new conversation.
* **Voice notes** are transcribed with the same `Transcriber` as CP-0051 and answered in text; images and documents get a one-time "please type" notice.
* **Privacy.** The user's full WhatsApp address is stored in one column, never in events, logs or API responses, and cleared after a retention period.
* **Runbook.** Console steps for the sandbox and for a production sender, the follow-up template wording, and a demo script ([/build/runbook-twilio-handover-whatsapp.md](/build/runbook-twilio-handover-whatsapp.md)).

# Affected specs

* [/architecture/whatsapp-channel.md](/architecture/whatsapp-channel.md) - new (WA-01 to WA-16)
* [/architecture/escalation.md](/architecture/escalation.md) - WhatsApp text conversations stay open (ES-14, shared with CP-0051)
* [/architecture/agent-desk.md](/architecture/agent-desk.md) - channel replies and masked address (DESK-12, shared)
* [/ui/agent-desk.md](/ui/agent-desk.md) - WhatsApp panel additions (UI-94, UI-95)
* [/data/data-model.md](/data/data-model.md) - `whatsapp_senders`, `whatsapp_threads`, `conversations.source` gains `whatsapp` (DM-20)
* [/api/rest-api.md](/api/rest-api.md) - `whatsapp-senders` (API-20), `channel_state` and delivery (API-23)
* [/process/conventions.md](/process/conventions.md) - prefix `WA`
* [/build/runbook-twilio-handover-whatsapp.md](/build/runbook-twilio-handover-whatsapp.md) - new

# Acceptance criteria

New: WA-01 to WA-16, UI-94, UI-95, DM-20, API-20, API-23 (shared with CP-0051), ES-14, DESK-12. No existing ID is reused.

# Dependencies

* **CP-0049 must land first**: the human message channel (`/architecture/human-message-channel.md`, HMC-01 to HMC-08, the `human` event kind, `POST /api/escalations/{id}/messages`, the console conversation panel UI-86). That spec is not in this branch, so this CP does not edit it; at merge, HMC-04's `wrong_channel` rule changes from "API text conversation" to "API or WhatsApp text conversation" and HMC-05 is unchanged.
* The `Transcriber` interface comes from CP-0051 (a voice-note task can wait for it; the rest of the channel does not need it).

# Tasks

1. Spec edits (done in this CP).
2. **Spikes S6 to S8** in the Twilio sandbox (status receipt field names and the out-of-window error, voice note type and download, username payloads); record findings here and adjust the spec.
3. Backend: tables (DM-20), sender API and CLI (WA-01, API-20), signed inbound and status routes (WA-02, WA-03, WA-15), thread and window logic (WA-04, WA-09), text turn integration (WA-05, ES-14), human delivery adapter and queue (WA-06 to WA-08), opt-out (WA-10), attachments and voice notes (WA-11), privacy and retention (WA-12), resolve and idle rules (WA-13, WA-14), `channel_state` and `delivery` (API-23), `mask.py` extension, settings and `/healthz`.
4. Web: panel additions (UI-94, UI-95) on CP-0049's conversation panel.
5. `scripts/fake_twilio.py --whatsapp` to post signed inbound and status requests and play receipts (no network); tests with a stubbed Twilio client citing the IDs; baseline lines for UI IDs awaiting a click-through and WA-16 (by hand).

# Risks and rollout

* **Sandbox limits** (3-day join, 1 message per 3 s, no custom templates) shape the demo: keep it inside the window; the template path is tested with a stub and proven only on a production sender.
* **Production** needs Meta business verification (weeks), an approved template and a number not already on WhatsApp; whether a US number suits Indian customers, India fees and Indian rules for WhatsApp are unverified; none is a blocker for the sandbox.
* **Privacy trade-off:** replying needs the address, so the "last four digits only" phone rule is relaxed for one column with retention; this is an owner decision (below).
* **Unverified Twilio behaviours** (webhook timeout and retry, BSUID or username payloads, receipt field names) are handled defensively: immediate response, duplicate `MessageSid` ignored, payloads without a usable `From` ignored.
* A voice note costs a transcription call; the 10 MB and 120 s caps bound it.

# Out of scope

* Meta's Cloud API directly and the WhatsApp Business Calling API; marketing or business-initiated messages; rich messages (buttons, lists, carousels); images and documents understanding; outbound broadcasts; group chats; the external chat app (CP-0049).

# Implementation status (2026-11-17)

`cp_state` stays `accepted`: the code is built and tested on fakes, but task 2 (spikes S6 to S8) and WA-16 need a Twilio account and a phone.

* **Done and tested** (`apps/api/tests/test_whatsapp.py`, 34 tests: Twilio REST on an httpx MockTransport, webhooks signed with the real algorithm and a test token, the repo's fake LLM, CP-0051's `FakeTranscriber`, temp SQLite, a fake pacing clock): task 3 (WA-01 to WA-15, DM-20, API-20, API-23, ES-14, DESK-12, HMC-04 widened to WhatsApp; `voiceai/whatsapp.py`, `voiceai/routes/whatsapp.py`, `voiceai whatsapp add|list|remove`, `/healthz` `providers.whatsapp`, settings, `mask.py` masks `whatsapp:+...`), task 5 (`scripts/fake_twilio.py --whatsapp` and `--whatsapp-receipt`). DM-01 now counts 43 tables. Task 4 (web: `components/whatsapp-panel.tsx` in the console) passes type check and build; UI-94 and UI-95 are in `scripts/acceptance-baseline.txt` (no browser click-through).
* **Not done**: task 2, spikes S6 to S8 (no Twilio account); WA-16 (by hand, baselined).
* **Unverified Twilio points, implemented as documented**: the receipt fields (`MessageSid`, `MessageStatus`, `ErrorCode`; `SmsSid` and `SmsStatus` also accepted) and the out-of-window error (code 63016 on a 400, which triggers the one template fallback on a production sender); the template is sent through the Messages API with `ContentSid` and `ContentVariables` `{"1": first name of the specialist}`, not a separate Content API call; a voice note is downloaded with HTTP Basic (account SID and token), its length is read from a WAV or an Ogg Opus header (any other format is limited by the 10 MB cap only) and the raw bytes go to the `Transcriber` (Deepgram detects the container; no transcoding is done, so a real Ogg Opus note may need ffmpeg if the provider refuses it); a payload with no usable `From` (a user with a username) is ignored with a warning; webhook retries are absorbed by the repeated-`MessageSid` check on the latest message only.
* **Choices the spec left open**: the thread is created in the webhook request itself (so a retry is caught) and the turn runs in a background task, one message at a time per thread; `channel_state` also carries `address_last4` (for the console's `wa-...1234`); a stored specialist reply starts with `delivery: sending` and ends `sent`, `queued_template` or `failed` before the response returns; a failed send is shown, never retried; the persona's welcome already says it is a virtual assistant, so the disclosure line is added only when the first reply does not start with it; the idle sweep and the address retention run in the job worker's one-minute sweep; a conversation that ended for any reason makes the next message open a new one.
