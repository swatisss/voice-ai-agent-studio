---
type: Component Spec
title: Contact tools - email, SMS and message calls
description: Three built-in tools on every agent and every channel - send_email (Brevo), send_sms and place_call (Twilio) - that send the caller details to the registered contact of a verified member or to an address the caller gives, after a read-back; masked records, a per-call limit, an outbox when no provider is configured and never a real delivery from a simulation.
status: stable
tags: [architecture, tools, messaging, email, sms, telephony, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Why

Callers often need details they can keep: a claim status, the documents a claim needs, a reference number, opening hours. Saying them aloud is easy to forget, and in a text chat the caller may want them somewhere else. Every agent can now send them by **email**, **text message (SMS)** or an **automated message call** that reads them aloud ([CP-0038](/changes/cp-0038-contact-tools.md)).

# The tools

Three built-in tools ([/architecture/agent-runtime.md](/architecture/agent-runtime.md), Built-in tools) are offered on **every agent** (inbound, outbound and internal, with or without HTTP tools) in **every channel**: text calls, cascade and realtime voice calls, phone calls, `/v1` conversations and simulations. There is no per-agent switch. Tenant tools may not use these names (TS-06).

| Tool | Arguments | Delivered by |
|---|---|---|
| `send_email` | `to` (`"registered"` or an email address), `subject` (1-120 characters), `message` (1-2,000), `confirmed` (boolean) | Brevo transactional email |
| `send_sms` | `to` (`"registered"` or a phone number with country code), `message` (1-480), `confirmed` | Twilio Messaging |
| `place_call` | `to` (`"registered"` or a phone number with country code), `message` (1-600), `confirmed` | Twilio Voice: an automated call that reads the message twice and hangs up; no conversation |

# Recipients

* **`to: "registered"`** means the contact on the member's record. It needs a **verified** call (level *verified*; *attested* is not enough because sending is an action, [/architecture/caller-verification.md](/architecture/caller-verification.md)). The runtime reads the contact from the business API (`MEMBER_CONTACT_URL`, default `/mock/healthcare/members/me/contact`, with `X-Member-Ref`, [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md)) at the moment it is needed: `email` for `send_email`, `mobile` for `send_sms` and `place_call`. The full address never reaches the model, the transcript or the database; the model sees it masked.
* **Any other `to`** is an address the caller gave in this call. Email: one `@`, a dot in the domain, no spaces, at most 254 characters, stored lower-case. Phone: spaces, dashes, dots and brackets are removed; the result must be `+` followed by 8-15 digits (E.164), so the model must add the country code. It is used for this one message and **never** saved to the member's record: changing contact details still goes to a person ([/architecture/caller-verification.md](/architecture/caller-verification.md)).
* **Unverified callers** may use their own address for **general information only** (how to file a claim, what documents are needed). The model has no member data before verification, so it has none to send; the prompt says so as well.

# Read-back before sending

Every tool works in two steps:

1. `confirmed: false` sends nothing and returns `{"status": "needs_confirmation", "channel", "to", "say"}`. For the registered contact `to` is masked (`m***@example.com`, `***0141`) and `say` is "Shall I send it to your email on file, m***@example.com?" (or "your mobile number ending 0141"); for an address the caller gave, `to` is the normalised address so the agent can read it back (an email spelled out) and `say` is "Just to confirm, that's maria.l@example.org?".
2. The model sets `confirmed: true` only after the caller has said yes to that exact address ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md), Sending details). Only then is anything sent.

# Execution

In this order, for `confirmed: true` (steps 1-4 also run for `confirmed: false`):

1. **Arguments.** Missing or empty `message`, or a message or subject over its limit → `{"error": "message_too_long"}` / `{"error": "invalid_arguments"}`. A malformed address → `{"error": "invalid_email" | "invalid_phone", "say": "..."}` asking for it again (with the country code for a phone).
2. **Registered contact.** Unverified call → `{"error": "identity_not_verified", "say": ...}` with the same texts as the verification gate (TS-01, TS-11); no lookup. No contact of that kind on the record → `{"error": "no_registered_email" | "no_registered_phone", "say": "There's no email address on your record. Which address should I use?"}`. The lookup itself failing → `{"error": "contact_unavailable"}`.
3. **Content guard.** A `message` or `subject` containing the verified member reference (case-insensitive) → `{"error": "member_id_in_message", "detail": "Leave the member ID out of the message and send again."}`: callers never get their full member ID read back or written down ([/product/healthcare-compliance.md](/product/healthcare-compliance.md) rule 4).
4. **Limit.** At most **3** confirmed sends per call, across the three tools and including failed ones; the next returns `{"error": "message_limit", "say": "I can't send any more messages on this call."}`.
5. **Deliver** through the channel's provider (below). Accepted → `{"status": "sent", "channel", "to": <masked>}`. Provider error, timeout (10 s) or rejection → `{"error": "delivery_failed", "say": "I couldn't send that just now."}`.
6. **Record** one `contact_messages` row ([/data/data-model.md](/data/data-model.md)) with the masked recipient, and a `tools_used` summary such as `send_email: sent to m***@example.com`.

Only `delivery_failed` and `contact_unavailable` count toward the tool-error streak (ES-03); the other refusals are answers the model acts on, like the verification gate. `identity_not_verified` does not count a failed verification attempt.

Tool arguments go through the Hindi normaliser of [/architecture/languages.md](/architecture/languages.md) for `to` only: `subject` and `message` are written in the caller's language and are sent exactly as the model wrote them.

# Providers

Each channel has a provider, chosen from the environment at the moment of sending:

| Setting | Values | Default |
|---|---|---|
| `EMAIL_PROVIDER` | `brevo`, `outbox` | `brevo` when `BREVO_API_KEY` and `EMAIL_FROM` are set, otherwise `outbox` |
| `SMS_PROVIDER` | `twilio`, `outbox` | `twilio` when `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM_NUMBER` are set, otherwise `outbox` |
| `CALL_PROVIDER` | `twilio`, `outbox` | as `SMS_PROVIDER` |

A provider named explicitly but missing its settings fails each send with `delivery_failed` (status `failed`, error `not_configured`).

* **Brevo** (email): `POST {BREVO_API_BASE}/v3/smtp/email` (default base `https://api.brevo.com`) with header `api-key: <BREVO_API_KEY>` and JSON `{"sender": {"email": EMAIL_FROM, "name": EMAIL_FROM_NAME or the tenant name}, "to": [{"email": <to>}], "subject": <subject>, "textContent": <message>}`. HTTP 201 → `provider_ref` = `messageId`. Brevo's free plan sends 300 emails a day; `EMAIL_FROM` must be a sender verified in Brevo.
* **Twilio SMS**: `POST {TWILIO_API_BASE}/2010-04-01/Accounts/{sid}/Messages.json`, HTTP basic auth (`sid`, token), form fields `To`, `From` (`TWILIO_FROM_NUMBER`), `Body`. HTTP 201 → `provider_ref` = `sid`.
* **Twilio message call**: `POST {TWILIO_API_BASE}/2010-04-01/Accounts/{sid}/Calls.json`, same auth, form fields `To`, `From`, `Twiml`. The TwiML reads the message, pauses one second, says "Here is the message again." and reads it again, then hangs up; the message is XML-escaped. A message with a Devanagari letter uses `language="hi-IN" voice="Polly.Aditi"` and the line "संदेश फिर से सुनिए।"; otherwise `language="en-US"`. The call is placed through Twilio's REST API only: no media stream, no webhook and no public URL are needed ([/architecture/telephony.md](/architecture/telephony.md)).
* **Outbox**: nothing leaves the platform. The message is recorded with status `outbox` and shown on the call detail; the model hears `sent`, so demos and local runs need no account.

A Twilio trial account sends SMS and places calls only to numbers verified in the Twilio console and prefixes them with a trial notice; that is Twilio's rule, not the platform's.

**Never from a simulation.** Calls of the `simulation` channel and evaluation calls (test suites, fix evaluations) never use a provider: their messages are recorded with status `simulated` and no HTTP request is made, whatever the settings.

**Redirect for testing.** With `CONTACT_REDIRECT_EMAIL` or `CONTACT_REDIRECT_PHONE` set, every real email or SMS/call goes to that address instead; the row keeps the intended masked recipient and `redirected: true`, and a redirected email's subject starts with `[for m***@example.com] `. The seeded members' contacts are fictional (`@example.com`, `555-01xx`), so this is how the registered-contact path is tried with a real phone or inbox.

# What the Studio shows

`GET /api/calls/{id}` lists `contact_messages` ([/api/rest-api.md](/api/rest-api.md)); the call detail shows them in a **Messages sent** card ([/ui/calls.md](/ui/calls.md)). `/healthz` reports the provider of each channel ([/architecture/deployment.md](/architecture/deployment.md)).

# Acceptance

- **CT-01** — Given any agent (inbound, outbound or internal; with or without HTTP tools), when a text turn requests the model and when a realtime session is configured, then the tool list contains `send_email`, `send_sms` and `place_call` with the arguments above.
- **CT-02** — Given an unverified call, when the model calls `send_email` with `to: "registered"`, then no contact lookup or delivery happens, the result is `identity_not_verified` with the verification gate's say text (the cannot-verify text on an agent without a verification tool), and neither the tool-error streak nor the verification attempts increase.
- **CT-03** — Given a call verified as EVG-482913, when `send_email` is called with `to: "registered"` and `confirmed: false`, then nothing is sent and the result is `needs_confirmation` with `to` `m***@example.com`; when called again with `confirmed: true`, then the email provider receives `maria.lopez@example.com`, the result is `sent` with the masked address, one `contact_messages` row has `destination: registered` and `to_masked: m***@example.com`, and the full address appears in no `contact_messages` row, call event or call `meta`.
- **CT-04** — Given a call verified as EVG-610277 (no registered mobile), when `send_sms` is called with `to: "registered"`, then the result is `no_registered_phone` with a say text asking for a number and nothing is sent.
- **CT-05** — Given `to` values "maria at example", "12345" and "+1 (202) 555-0199", then `send_email`/`send_sms` return `invalid_email`, `invalid_phone` and, for the third, `needs_confirmation` with `to: "+12025550199"`; after `confirmed: true` the message goes to `+12025550199`, the row has `destination: other` and `to_masked: ***0199`, and no request is made to change the member's record.
- **CT-06** — Given a verified call, when a `message` contains the member reference ("evg-482913"), then the result is `member_id_in_message` and nothing is sent; given a message of 481 characters to `send_sms`, the result is `message_too_long`.
- **CT-07** — Given three confirmed sends in one call (any tools), when a fourth is confirmed, then the result is `message_limit` and nothing is sent.
- **CT-08** — Given `BREVO_API_KEY` and `EMAIL_FROM` set, when an email is sent, then one `POST /v3/smtp/email` is made with the `api-key` header and the sender, recipient, subject and text above; HTTP 201 with a `messageId` records status `sent` and that `provider_ref`; HTTP 400 records status `failed`, returns `delivery_failed` and increases the tool-error streak.
- **CT-09** — Given the three Twilio settings, when an SMS is sent, then one `POST .../Messages.json` is made with basic auth and form `To`, `From`, `Body`; when a message call is placed, then one `POST .../Calls.json` is made whose `Twiml` contains the XML-escaped message twice in `<Say language="en-US">`; a Devanagari message uses `language="hi-IN"`.
- **CT-10** — Given no provider settings, when an email, an SMS and a call are confirmed, then no HTTP request leaves the platform, each row has status `outbox` and provider `outbox`, and the model's result is `sent`; given a simulation or evaluation call with all providers configured, then no HTTP request is made and each row has status `simulated`.
- **CT-11** — Given `CONTACT_REDIRECT_EMAIL` set, when an email to the registered contact is confirmed, then Brevo receives the redirect address, the subject starts with `[for m***@example.com] `, and the row keeps `to_masked: m***@example.com` with `redirected: true`.
- **CT-12** — Given a bilingual call, when `send_sms` is called with a Devanagari `message` containing "१४ मार्च" and `to` "+९१ ९८७६५ ४३२१०", then the message is delivered exactly as written and `to` is normalised to `+919876543210`.
