---
type: Change Proposal
title: CP-0038 Contact tools - email, SMS and message calls
description: Every agent, in every channel, can send the caller details by email (Brevo), SMS or an automated message call (Twilio) - to a verified member's registered contact or to an address the caller gives, after a read-back - with masked records, a per-call limit, an outbox when no provider is set and no real delivery from simulations.
status: stable
cp_state: implemented
tags: [tools, messaging, runtime, telephony, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

# Why

The owner wants agents to send callers the details they need to keep: "this is your registered email (or phone), can I use it to send the details, or do you want to give another one?", and the same for callers who are not registered members. Today an agent can only speak: details are forgotten after the call, and the only "email" the platform knows is the mock `request_document` delivery option. [/product/scope.md](/product/scope.md) lists "SMS ... for end customers" as out of scope.

**Owner's decisions (2026-11-12):**

* **Providers:** Brevo for email (free plan, 300 emails a day), Twilio for SMS and calls (the account already used for inbound phone calls; a trial account works with verified numbers). Options compared: Resend, Mailjet, SendGrid (no free plan any more) for email; Telnyx, Plivo, Vonage, Exotel and MSG91 for SMS and voice.
* **Always present:** the tools are on every existing and new agent, in voice and text alike; no per-agent switch.
* **"Call" means a message call:** Twilio phones the number and reads the message aloud, like a spoken SMS. A callback that connects the person to the AI agent for a conversation is a separate, later change (real outbound dialing stays out of scope).
* **Recipients:** a verified member is offered the registered contact first (read back masked) or may give another address, which is read back and confirmed; unverified callers may receive general information at an address they give. A new address is used once and never saved to the record.

**Acceptance:** the owner asked for this to be implemented in the same request and made the decisions above when asked, so the CP is recorded as accepted on 2026-11-12.

# What changes

* Three built-in tools on every agent and channel: `send_email`, `send_sms`, `place_call` ([/architecture/contact-tools.md](/architecture/contact-tools.md)).
* Two-step use: `confirmed: false` returns the (masked) address to read back; `confirmed: true` sends.
* The registered contact is read from the business API when needed (new mock endpoint `/members/me/contact`), never stored or shown to the model unmasked.
* Guards in code: verification before the registered contact; address validation (E.164 phones); no member ID in a message; at most 3 messages per call; simulations and evaluations never deliver.
* Providers from the environment: Brevo, Twilio, or an **outbox** (recorded, shown in the Studio, not delivered) when no provider is configured, so nothing changes for a setup without keys. Optional redirect of all real deliveries to a test inbox or phone.
* New table `contact_messages` (masked recipient, channel, provider, status); the call detail gets a **Messages sent** card; `/healthz` reports each channel's provider.
* The agent system prompt gets a **Sending details** block; bilingual agents write messages in the caller's language.

Example:

> Caller (verified Maria): "Can you send me the list of documents for the claim?"
> Agent: "Of course. Shall I send it to your email on file, m-star-star-star at example dot com?"
> Caller: "No, send it to maria dot l at example dot org."
> Agent: "Just to confirm, that's m-a-r-i-a dot l at example dot org?" Caller: "Yes." Agent: "Done, it's on its way."

# Affected specs

* [/architecture/contact-tools.md](/architecture/contact-tools.md) - **new**: tools, recipients, read-back, execution order, providers, outbox, redirect, simulations; CT-01..CT-12
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - Built-in tools table lists the three tools
* [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) - TS-06 covers the new reserved names
* [/architecture/languages.md](/architecture/languages.md) - message and subject are written in the caller's language and not normalised
* [/architecture/telephony.md](/architecture/telephony.md) - outbound SMS and message calls through the Twilio REST API
* [/architecture/deployment.md](/architecture/deployment.md) - `/healthz` `messaging` block (DEP-06)
* [/api/rest-api.md](/api/rest-api.md) - `contact_messages` on `GET /api/calls/{id}` (API-16)
* [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md) - `GET /members/me/contact` (MOCK-18)
* [/data/data-model.md](/data/data-model.md) - table `contact_messages` (38 tables, DM-01, DM-15)
* [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md) - each member's contact on file
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - Sending details block; Language block exception for messages
* [/product/scope.md](/product/scope.md) - sending email, SMS and message calls moves into scope
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - rule 13 and the production gaps for email and SMS
* [/product/compliance-evidence.md](/product/compliance-evidence.md) - control C15
* [/ui/calls.md](/ui/calls.md) - Messages sent card (UI-74)
* [/build/runbook-local.md](/build/runbook-local.md) - setting up Brevo and Twilio
* [/decisions/adr-0014-contact-providers.md](/decisions/adr-0014-contact-providers.md) - **new**: why Brevo and Twilio, the outbox, and message calls instead of AI callbacks

# Acceptance criteria

New: **CT-01..CT-12** in [/architecture/contact-tools.md](/architecture/contact-tools.md); **MOCK-18**; **DM-15** (DM-01 now counts 38 tables); **API-16**; **DEP-06**; **UI-74**. Changed: **TS-06** also rejects the three new names; **LANG-06** applies the normaliser to the `to` argument of contact tools only.

# Tasks

1. Spec edits (this CP).
2. Mock API `/members/me/contact` and setting `MEMBER_CONTACT_URL` — covers MOCK-18.
3. Table `contact_messages` — covers DM-01, DM-15.
4. `voiceai/contact.py`: validation, masking, providers (Brevo, Twilio SMS, Twilio call, outbox), redirect; `ToolExecutor` runs the three tools; built-in schemas; reserved names — covers CT-01..CT-12, TS-06, LANG-06.
5. Prompt: Sending details block and the Language block exception.
6. `GET /api/calls/{id}` `contact_messages`; `/healthz` `messaging` — covers API-16, DEP-06.
7. Web: Messages sent card on the call detail — covers UI-74 (checked by hand).
8. `.env.example`, runbook, compliance evidence C15; tests in `tests/test_contact_tools.py`.
9. Manual check (owner): one real email through Brevo and one SMS and message call through a Twilio trial to the owner's verified phone.

# Risks and rollout

* **Privacy.** Email and SMS are not end-to-end encrypted and free plans sign no Business Associate Agreement. Guards: verified-only registered contact, read-back, no member ID in messages, prompt rule for minimum necessary content, synthetic data only. A model could still put more detail in a message than needed; call scoring and reviewers see every message on the call detail.
* **Abuse.** An unverified caller could make the agent send messages to any address; capped at 3 per call, and the agent has no member data to send before verification. Production would add per-number rate limits.
* **Cost and limits.** Brevo free: 300 emails/day; Twilio charges per SMS segment and per call minute (trial credit first). Hindi SMS use UCS-2: 70 characters per segment.
* **Latency.** A send is a synchronous provider request (usually under a second, at most 10 s) inside a tool round; voice callers hear the filler line.
* **Rollout.** No keys → outbox, so existing setups and tests change only by three more tools in every request. Existing agents get the tools at once because they are built in, not part of the version snapshot. The prompt block adds about 150 tokens per request.

# Out of scope

* AI callbacks (Twilio connects the person to the voice agent) and any real outbound dialing for conversations.
* Two-way SMS or chat over SMS/WhatsApp; delivery receipts and bounce webhooks (the status is what the provider answered at send time).
* Saving a new contact to the member's record; marketing messages; attachments and HTML email templates.
* A per-agent switch or per-tenant provider keys (one platform account per provider).
