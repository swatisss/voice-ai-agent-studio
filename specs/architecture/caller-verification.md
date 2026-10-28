---
type: Component Spec
title: Caller verification
description: How a call learns who the caller is - identified by a registered phone number, verified by date of birth (registered number) or member ID and date of birth (any number) - with attempt limits, attestation and testing in the playground.
status: stable
tags: [architecture, verification, telephony, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Levels

| Level | How it is reached | What the agent may do |
|---|---|---|
| **Unknown** | Start of every call | General information only (how deductibles work, how to add a newborn) |
| **Identified** | The calling number is registered on a member's record | Address the caller by first name and ask only for the date of birth. No member data, no profile, no memory. |
| **Verified** | Registered number + date of birth (flow A), or member ID + date of birth (flow B) | Member-specific tools, the member profile and member memory ([/architecture/agent-memory.md](/architecture/agent-memory.md)) |

A phone number alone never verifies a caller: caller ID can be spoofed and is cryptographically checked only in some countries ([ADR-0010](/decisions/adr-0010-caller-verification.md)). The level is part of the call state and is never inferred from the IVR or outbound context ([/architecture/call-modes.md](/architecture/call-modes.md)).

# Identification

* **Phone calls**: the Twilio webhook passes the caller's `From` number to the business API's identify endpoint (`POST /mock/healthcare/identify {phone}`, [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md)) before the call is created. A match returns `{matched: true, member_ref, first_name}`; a withheld number (`anonymous`, `unknown`, empty) is not looked up. The call stores `meta.identification = {member_ref, first_name, method: "caller_id", attestation}`, where `attestation` is Twilio's `StirVerstat` value or `null`. The full caller number is still never stored ([/architecture/telephony.md](/architecture/telephony.md)).
* **Browser test calls**: `POST /api/calls` accepts an optional `caller_number`; the platform runs the same lookup, so the playground exercises both flows without a phone ([/ui/test-call.md](/ui/test-call.md)).
* Outbound calls are not identified by number; the callee verifies as in flow B ([/prompts/mode-outbound.md](/prompts/mode-outbound.md)).

# Verification

* **Flow A — identified caller**: the prompt says the caller appears to be `{first_name}` and asks for the date of birth only. The verification tool is called with `{date_of_birth}`; the tool executor adds header `X-Identified-Ref` with the identified member reference, and the business API checks the date of birth against that member ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)).
* **Flow B — anyone else**: member ID and date of birth, as before.
* If an identified caller says they are someone else, the agent uses flow B.
* **Attestation shortcut** (per agent, `verification.trust_attested_caller_id`, default `false`, labelled "demo only"): a call identified with attestation `TN-Validation-Passed-A` starts verified at level *attested* for read-only tools (`GET`); tools that change data (`POST`) still return `identity_not_verified` until the date of birth is confirmed. Any other attestation, or none, is flow A.

# Failures

* A verification tool result with `verified: false` counts one attempt. The agent always hears the same message, which never says which item was wrong: "I'm sorry, I couldn't verify those details." The business API's reason is not passed to the model.
* After the third failed attempt in a call, the runtime escalates with category `verification_failed` and says the hand-off message ([/architecture/escalation.md](/architecture/escalation.md)). Lockout across calls is out of scope.
* Requests to change contact or identity details (address, phone, email, bank details, authorised representatives) are handed to a human: there is no step-up factor in this version.

# Testing with Twilio

There is no Twilio voice simulator. Flow A is tested with a phone or Twilio Dev Phone whose number is registered on a synthetic member, or by placing a call through the Calls API from a second Twilio number; see [/build/runbook-phone.md](/build/runbook-phone.md).

# Acceptance

- **IDV-01** — Given a signed Twilio webhook with `From` equal to Maria Lopez's registered number, when the call is created, then `meta.identification` holds `EVG-482913`, `Maria`, method `caller_id` and the `StirVerstat` value, the call is not verified, and no full caller number is stored anywhere.
- **IDV-02** — Given an identified call, when the caller gives the correct date of birth, then the verification tool is called with only the date of birth, the request carries `X-Identified-Ref: EVG-482913`, and the call becomes verified with `verified_member_ref` `EVG-482913`.
- **IDV-03** — Given a call from an unregistered or withheld number, then it is not identified and verification asks for member ID and date of birth.
- **IDV-04** — Given three failed verification attempts in one call, then the call is escalated with category `verification_failed`, the hand-off message is the last agent line, and each failure message is identical.
- **IDV-05** — Given an identified call with attestation `TN-Validation-Passed-A` on an agent with `trust_attested_caller_id: true`, then a `GET` tool marked `requires_verification` runs and a `POST` one returns `identity_not_verified` until the date of birth is confirmed; with the setting off, both are blocked until verification.
- **IDV-06** — Given a browser text call started with `caller_number` set to a registered number, then the call is identified exactly as a phone call would be; with an unknown number or none, it is not.
- **IDV-07** — Given an identified call, then before verification the prompt contains the caller's first name but no member profile, memory, member ID or date of birth.
