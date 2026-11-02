---
type: Change Proposal
title: CP-0036 Carrier adapters - telephony that any carrier or SIP source can plug into
description: Twilio-specific telephony code moves behind one carrier-adapter interface with a registry and carrier-named routes, so another carrier or the customer's own Asterisk can be added as one module; Twilio stays the only adapter and phone calls behave exactly as before.
status: draft
cp_state: accepted
tags: [telephony, sip, architecture]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-02T00:00:00Z" }
---

# Why

The product owner (2026-11-02) wants the platform ready for any SIP source without adding a carrier now. Today the telephony module, routes and serializer are written for Twilio only. [ADR-0013](/decisions/adr-0013-carrier-adapters-and-sip-paths.md) records how Dograh and others reach SIP without UDP on their own servers, and decides on carrier adapters.

# What changes

1. A **carrier adapter** interface and registry ([/architecture/telephony.md](/architecture/telephony.md), Carrier adapters). Twilio becomes the `twilio` adapter: signature check, inbound call fields, TwiML answer and refusal, the mu-law serializer, REST transfer, configured check.
2. Routes become `/api/telephony/{carrier}/voice`, `/api/telephony/{carrier}/stream/{call_id}` and `/api/telephony/{carrier}/conversation/{conversation_id}`; for `twilio` the URLs are the ones in use today. An unregistered carrier answers 404 `unknown_carrier`.
3. `meta.telephony.provider` is the adapter's name (already `twilio`); `/healthz` `providers.twilio` comes from the adapter's configured check.
4. Scope and ADR text: SIP reaches the platform through a carrier's SIP trunk (works today with Twilio), the customer's own Asterisk over WebSocket (next adapter) or a speech model's own SIP endpoint.

# Affected specs

* [/decisions/adr-0013-carrier-adapters-and-sip-paths.md](/decisions/adr-0013-carrier-adapters-and-sip-paths.md) (new)
* [/architecture/telephony.md](/architecture/telephony.md) - Carrier adapters section; TEL-13
* [/product/scope.md](/product/scope.md) - the telephony line names the SIP paths

# Acceptance criteria

Defined in [/architecture/telephony.md](/architecture/telephony.md): **TEL-13** (the carrier registry; TEL-01…TEL-12 unchanged).

# Tasks

1. Spec edits (this CP).
2. `voiceai/telephony/` package: shared helpers (tokens, IVR context, public URL) in `__init__`, the `CarrierAdapter` protocol and registry, `twilio.py` adapter; routes take `{carrier}` — TEL-13.
3. Existing telephony tests unchanged; new test for TEL-13.

# Risks and rollout

Pure restructuring for callers: Twilio numbers keep their webhook URL. Risk is a missed import; the existing TEL tests and `scripts/fake_twilio.py` catch it.

# Out of scope

A second carrier, the Asterisk adapter, direct SIP to a speech model, outbound dialing, DTMF.
