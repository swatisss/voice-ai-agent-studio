---
type: Component Spec
title: WhatsApp channel (Twilio)
description: "WhatsApp through Twilio as a text channel into the platform - sandbox first, a production sender later - with the AI answering, escalation to Agent Desk over the human message channel, the 24-hour window with a template for late replies, opt-out, and voice notes transcribed."
status: draft
tags: [architecture, whatsapp, twilio, channels, escalation, privacy]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Purpose

A customer can message a WhatsApp number and talk to the same agents as in the Studio or on the phone. WhatsApp is **another transport for a text conversation**, like the public API ([/api/public-api.md](/api/public-api.md)): the brain, tools, safety screen, verification, routing and escalation are unchanged. After an escalation the conversation stays open and a specialist answers from Agent Desk through the **human message channel** (`/architecture/human-message-channel.md`, CP-0049, HMC-01 to HMC-08, adopted as designed: customer lines stored for the human, specialist replies posted to `POST /api/escalations/{id}/messages`, console events). This spec adds the Twilio delivery, the WhatsApp window and the WhatsApp-specific rules. Twilio facts and the points still to be confirmed (spikes S6 to S8) are in `.scratch/human-voice-and-channels/research/03-twilio-handover-whatsapp.md`.

Only Twilio is supported. A second provider (Meta's own Cloud API) would be one more adapter and its own CP.

```
WhatsApp user ─▶ Twilio WhatsApp sender ─▶ POST /api/channels/twilio/whatsapp/inbound  (signed form)
                                              │ finds or opens the thread and the conversation, answers 200 <Response/> at once
                                              ▼ background: text turn (same code as POST /v1 …/messages) → reply by Twilio REST Messages
Agent Desk ─▶ POST /api/escalations/{id}/messages ─▶ human event ─▶ delivery adapter ─▶ Twilio REST (free-form, or template when the window is closed)
Twilio ─▶ POST /api/channels/twilio/whatsapp/status  (delivery receipts)
```

# Senders

A sender is a WhatsApp address that belongs to one tenant and routes to one agent or the front desk. Table `whatsapp_senders` ([/data/data-model.md](/data/data-model.md), DM-20): `address` (`whatsapp:+E164`, unique across all tenants), `mode` (`sandbox`|`production`), `target` (`agent`|`front_desk`), `agent_id`, `label`. API `GET/POST/DELETE /api/whatsapp-senders` (admin; [/api/rest-api.md](/api/rest-api.md), API-20) and the CLI `uv run voiceai whatsapp add <address> --front-desk|--agent <name or id> [--production] [--label ...]`, `whatsapp list`, `whatsapp remove`. The Twilio sandbox number is `whatsapp:+14155238886`, shared by every sandbox user; the same row type serves a production sender.

* The address must match `^whatsapp:\+[1-9][0-9]{6,14}$`; a duplicate is 409 `sender_in_use`; an unknown or other-tenant agent is 422; another tenant's sender is 404.
* As with phone numbers this is the one place a request is routed to a tenant without a tenant header ([/architecture/multi-tenancy.md](/architecture/multi-tenancy.md)); the tenant is the row's.
* Whether a front-desk sender needs a routable member agent is checked as for phone numbers (call admission, [/architecture/call-admission.md](/architecture/call-admission.md)).

# Inbound — `POST /api/channels/twilio/whatsapp/inbound`

Twilio posts a form with `MessageSid`, `From` and `To` (`whatsapp:+E164`), `Body`, `NumMedia`, `MediaUrl0`, `MediaContentType0` and `ProfileName`. Steps:

1. **Validate `X-Twilio-Signature`** exactly as the phone webhook does ([/architecture/telephony.md](/architecture/telephony.md), Request security: full URL from `PUBLIC_BASE_URL`, sorted fields, constant-time compare; `TWILIO_VALIDATE_SIGNATURE=0` only off Cloud Run, TEL-10). For this route the signed URL keeps its port. Invalid: 403, nothing stored.
2. Look up `To` in `whatsapp_senders`. Unknown sender, a missing credential, or a refusal by admission: answer 200 with an empty `<Response/>` and do nothing (a WhatsApp user has no use for a spoken error).
3. **Answer at once** with an empty `<Response/>` (200). Everything below runs in the background; the reply is sent with Twilio's REST API, so a slow model never makes the webhook time out. A repeated `MessageSid` is ignored.
4. **Find the thread** (table `whatsapp_threads`, DM-20): the open thread for this sender and this user address. The first message creates a conversation (`source: whatsapp`, `channel: text`, `transport: twilio`, scope `member`) and a thread. `last_inbound_at` is set to now and `window_expires_at` to 24 hours later on **every** inbound message.
5. **Opt-out.** A message that is exactly `STOP`, `UNSUBSCRIBE` or `CANCEL` (any case, trimmed) marks the thread `opted_out`, sends one confirmation ("You will not get more messages from us. Message us again any time to start over.") and stops all outbound. A later inbound message from the same user clears `opted_out` and counts as a new request.
6. **Text turn.** The text (or a voice note's transcript) runs through the conversation's text turn like a public API message, including the safety screen and the request-for-a-person rule ([/architecture/escalation.md](/architecture/escalation.md), ES-01, ES-13). The first reply of a new conversation starts with the disclosure line "I'm a virtual assistant for {tenant name}." followed by the agent's welcome (the persona's own welcome already opens with a virtual-assistant disclosure, in which case nothing is added). Replies are plain text (no markdown) of at most 1,500 characters; longer text is split on sentence boundaries into several messages, sent in order.
7. **Escalation.** When the turn escalates, the hand-off message is sent and the conversation is `escalated` as in HMC. From then on a customer message is stored as a `user` event with `to_human: true`, no model runs, nothing is replied (HMC-01).

Delivery is paced: `WHATSAPP_MIN_SEND_INTERVAL_S` seconds between sends per sender (default 3 for a `sandbox` sender, which Twilio limits to one message per 3 seconds; 0 for `production`).

# Voice notes and attachments

* `NumMedia ≥ 1` with an **audio** `MediaContentType`: the platform downloads the file (Twilio's media URL; HTTP Basic with the account credentials when required, spike S7), refuses more than 10 MB or 120 seconds ("I couldn't process that voice note. Could you type your message?"), and transcribes it with the `Transcriber` of [/architecture/phone-warm-handover.md](/architecture/phone-warm-handover.md) (language hints from the agent's `languages`, so a Hindi or Hinglish note works with the provider chosen there). The transcript is the customer's text for the turn; the event carries `data.voice_note: true`. The reply is text. The audio is never stored.
* An image, PDF or other file: no processing. The customer is told once per thread "I can't read pictures or documents yet. Please type what you need."; if the conversation is escalated the specialist sees the event text `[attachment: image/jpeg]`. Nothing is downloaded.
* Text sent with an attachment is handled as text.

# Specialist replies and the 24-hour window

The reply endpoint is CP-0049's `POST /api/escalations/{id}/messages {text}`; its `wrong_channel` rule applies to conversations with `source: api` **or `whatsapp`** (changing HMC-04's wording is part of CP-0052). The reply is stored as a `human` event as designed there, then handed to the **delivery adapter**:

| Window | Delivery |
|---|---|
| Open (`now < window_expires_at`) | Free-form text through Twilio's Messages API from the sender to the user. `data.delivery = "sent"`. |
| Closed | The text is **queued** (`data.delivery = "queued_template"`) and the approved follow-up **template** is sent instead, through the Messages API with `ContentSid` and `ContentVariables` (`{"1": <specialist's first name>}`; From and To as WhatsApp addresses). The template is fixed text that invites the customer to reply (the platform's suggested wording is in the runbook); when the customer replies the window opens and the queued texts are delivered in order. If no `TWILIO_WHATSAPP_FOLLOWUP_CONTENT_SID` is configured, the reply is 409 `template_not_configured` and nothing is stored. |
| The thread is `opted_out` | 409 `opted_out`, nothing stored, nothing sent. |

* A free-form send that Twilio rejects because the window had in fact closed (the clock and WhatsApp can differ by a moment) falls back to the template path once.
* The **sandbox cannot send a custom template** (only three pre-approved ones), so with a `sandbox` sender a closed window is 409 `window_closed` and the demo stays inside the window.
* `GET /api/escalations/{id}` (and the list) add `channel_state` for these conversations: `{channel: "whatsapp", window_open, window_expires_at, opted_out, mode, address_last4}` (API-23); Agent Desk shows the remaining time and the template notice ([/ui/agent-desk.md](/ui/agent-desk.md), UI-94, UI-95).
* **Status callbacks.** `POST /api/channels/twilio/whatsapp/status` (signed) receives Twilio's delivery receipts; the message status updates the matching `human` event's `data.delivery` (`sent`, `delivered`, `read`, `failed`, `undelivered`) and publishes `escalation.updated` on topic `console`. A failed delivery shows to the specialist; nothing is retried automatically. The receipt's field names are confirmed in spike S6.
* **Resolving** the escalation ends the conversation (HMC-05). If the window is open, one closing message is sent: "This conversation has been closed by {first name}. Message us again any time." A customer message after that opens a **new** conversation (a WhatsApp user has no app to show a 409).
* **Customer leaving** is the customer not writing again: nothing ends the conversation until the specialist resolves it or the idle rule below applies.
* **Idle.** A thread with no inbound message for 72 hours and no escalation ends with `end_reason: idle`; one with an escalation stays until resolved.

# Privacy

A reply cannot be addressed without the user's WhatsApp address, so the phone rule "last four digits only" ([/architecture/telephony.md](/architecture/telephony.md)) is relaxed **for one column**:

* The full address is stored only in `whatsapp_threads.address`. It is never put in call events, `conversations.metadata`, logs, error messages, webhooks, the public or Studio API, or the Agent Desk. Everywhere else the user appears as `wa-…{last4}` (`address_last4`); `mask.py` also masks `whatsapp:+…` strings in free text ([/architecture/agent-desk.md](/architecture/agent-desk.md)).
* After the conversation ends the address is cleared after `WHATSAPP_ADDRESS_RETENTION_DAYS` (default 30, so a follow-up template can still reach the customer for that period) and the thread keeps only `address_last4`.
* `ProfileName` is not stored. Twilio may identify some WhatsApp users without a phone number; handling that is unverified and, until confirmed (spike S8), a payload without a usable `From` is ignored with a warning.
* Opt-in: a user's own first message is the opt-in (and, in the sandbox, their `join` message). The platform never sends a business-initiated message except the follow-up template inside an existing thread, within its retention period, and never to an `opted_out` thread. Whether Indian rules (TRAI, DPDP) add anything for WhatsApp is not verified and is an owner decision before production.
* Synthetic data only in demos and tests.

# Settings

| Variable | Meaning |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `PUBLIC_BASE_URL`, `TWILIO_VALIDATE_SIGNATURE` | As for the phone channel. |
| `TWILIO_WHATSAPP_FROM` | Optional default sender address (`whatsapp:+14155238886` for the sandbox); the sender row decides routing, this only names the sender used for outbound when a thread has none. |
| `TWILIO_MESSAGING_SERVICE_SID` | Optional `MG…`; when set, outbound uses it. |
| `TWILIO_WHATSAPP_FOLLOWUP_CONTENT_SID` | The approved follow-up template (`HX…`). |
| `WHATSAPP_MIN_SEND_INTERVAL_S` | Pacing per sender (default 3 sandbox, 0 production). |
| `WHATSAPP_ADDRESS_RETENTION_DAYS` | Default 30. |

`GET /healthz` adds `providers.whatsapp` (account credentials configured and at least one sender row; no network call, no values).

# Acceptance

- **WA-01** — Given the sender API, when senders are added, listed and removed, then the address format, 409 `sender_in_use`, 422 for an unknown agent, another tenant's sender as 404, admin-only access and the CLI mirror hold, and removing a sender makes its inbound webhook do nothing.
- **WA-02** — Given an inbound request with a missing or wrong `X-Twilio-Signature` (including one computed over a different URL), then 403 and no conversation; with a valid one, 200 with an empty `<Response/>`; `To` of an unknown sender is 200 with nothing created; `TWILIO_VALIDATE_SIGNATURE=0` follows TEL-10.
- **WA-03** — Given a mapped sender and a first signed message "Hi, what is my excess?", when it is posted, then the response is immediate and empty, one conversation (`source: whatsapp`, `channel: text`) and one thread with a 24-hour window exist, the agent's reply is sent through the Twilio Messages API (stubbed) beginning with the virtual-assistant disclosure, and the same `MessageSid` posted again creates no second turn.
- **WA-04** — Given an open thread, when a second message arrives, then the same conversation continues (no new conversation), `window_expires_at` moves to 24 hours after it, a reply longer than 1,500 characters is sent as ordered parts, and two sends from a `sandbox` sender are at least 3 seconds apart while a `production` sender has no delay.
- **WA-05** — Given the customer writes "I have chest pain" or "I want to speak to a human", then the safety message or the hand-off line is sent, an escalation (`safety` or `caller_requested`) is created and the conversation is `escalated`, with no model reply for those lines (ES-01, ES-13).
- **WA-06** — Given an escalated WhatsApp conversation, when the customer writes "Hello? Anyone there?", then it is stored as a `user` event with `to_human: true`, no LLM request is made and nothing is sent back (HMC-01).
- **WA-07** — Given an accepted escalation with the window open, when the specialist posts a reply, then it is stored as a `human` event, sent once as free-form text to the user's address, `data.delivery` is `sent`, and a status receipt `delivered` then `read` updates it and publishes `escalation.updated`; posting before `accept` is 409 `not_accepted` (HMC-03).
- **WA-08** — Given an accepted escalation whose window closed, when the specialist posts a reply, then with a `production` sender and a configured template the response is 201, `data.delivery` is `queued_template`, exactly one template message is sent with `ContentSid` and `ContentVariables`, and when the customer replies the queued text is sent as free-form; without the template setting 409 `template_not_configured` and nothing stored; with a `sandbox` sender 409 `window_closed`; a free-form send rejected as out of window falls back to the template once.
- **WA-09** — Given the escalation read of a WhatsApp conversation, then `channel_state` has `window_open`, `window_expires_at` (24 hours after the last inbound message), `opted_out` and `mode`, and a conversation of another source has none.
- **WA-10** — Given the customer sends "stop", then the thread is `opted_out`, one confirmation is sent and no further message is sent; a specialist reply is 409 `opted_out`; when the customer writes again the thread is active again.
- **WA-11** — Given an inbound voice note of 30 seconds, then it is downloaded, transcribed by the fake Transcriber, the transcript drives the turn with `data.voice_note: true` and the reply is text; a 130-second note or a 12 MB note gets the "type your message" reply and no model call; an image gets the one-time attachment notice and, when escalated, the event text `[attachment: image/jpeg]`; no media is stored.
- **WA-12** — Given any conversation, events, logs, webhook payloads and API responses, then the user's full WhatsApp address appears only in `whatsapp_threads.address`; Agent Desk responses show only `address_last4`; after the retention days following the end the column is cleared.
- **WA-13** — Given an accepted escalation, when the specialist resolves it, then the conversation is `ended` with `human_resolved`, one closing message is sent if the window is open, and the customer's next message opens a new conversation.
- **WA-14** — Given a thread with no inbound message for 72 hours and no escalation, then the conversation ends with `end_reason: idle`; with an escalation it stays open.
- **WA-15** — Given `GET /healthz`, then `providers.whatsapp` is `true` only with Twilio account credentials and one sender row, and no secret appears.
- **WA-16** — Given a Twilio account with the WhatsApp sandbox, the owner's phone joined with the sandbox code and the sandbox webhook pointed at the inbound route, when the owner messages the sandbox number, asks for a person and a specialist replies from Agent Desk, then the replies arrive on WhatsApp, the status receipts update the Desk, and a Hindi voice note is answered in text (checked by hand against a running server; spikes S6 to S8 pass).
