---
type: Decision Record
title: ADR-0010 Caller verification - registered number identifies, date of birth verifies
description: A call from a registered number is identified (first name only) and verified with the date of birth; any other call uses member ID and date of birth; caller ID alone never verifies. Records the research behind the choice.
status: stable
tags: [decision, verification, telephony, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Context

Callers verify with member ID and date of birth today ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)). Phone callers usually call from a number the insurer already holds, and asking them to read out a member ID is slow. Member memory and the member profile ([/architecture/agent-memory.md](/architecture/agent-memory.md)) raise the stakes of verifying the right person.

Research (2026-10-28):

* Health plans pair caller ID with a knowledge item and never accept it alone; published member IVRs accept member ID + DOB or caller ID + DOB. https://broker.healthalliance.org/flash/improved-member-call-in-experience/
* Caller-ID vendors say a number match alone "does not determine whether the displayed number has been spoofed" and use it as a risk signal. https://www.pindrop.com/product/vericall-technology/
* US STIR/SHAKEN attestation A/B/C; Twilio passes it on inbound calls as `StirVerstat` (`TN-Validation-Passed-A`, …, `No-TN-Validation`). https://www.twilio.com/docs/voice/trusted-calling-with-shakenstir · The UK (Ofcom) and Australia (ACMA) have no equivalent attestation. https://www.ofcom.org.uk/consultations-and-statements/category-2/cli-authentication · https://www.acma.gov.au/caller-id-scams
* HIPAA 45 CFR 164.514(h): verify identity before disclosing PHI with a reasonable procedure; UK GDPR Recital 64: reasonable measures scaled to sensitivity. (Summaries; check primary text before compliance wording.)
* Typical controls: 2–3 attempts then a human; uniform failure messages; never read identifiers back; step-up (one-time code or a human) for changes to contact or bank details; SMS codes are a "restricted" authenticator in NIST SP 800-63B rev 4. https://pages.nist.gov/800-63-3/sp800-63b.html
* There is no Twilio voice simulator: test with Twilio Dev Phone or a call placed through the Calls API. https://www.twilio.com/docs/labs/dev-phone

# Options

1. **Caller ID verifies by itself** — fastest; unsafe (spoofing) and not what health plans do.
2. **Caller ID identifies, date of birth verifies (flow A); member ID + DOB otherwise (flow B)** — the common health-plan pattern.
3. **Add a one-time code** — stronger, but SMS codes are a restricted authenticator and the demo has no SMS provider.

# Decision

Option 2, with an opt-in, demo-only shortcut: a US call with attestation `TN-Validation-Passed-A` may use read-only tools before the date of birth. Three failed attempts hand the call to a human; changes to contact or identity details always go to a human. See [/architecture/caller-verification.md](/architecture/caller-verification.md).

# Consequences

* The business API owns registered phone numbers; the platform keeps storing the last four digits only.
* A playground "Call from" choice exercises both flows without Twilio; real phone tests use Dev Phone or the Calls API.
* A step-up factor (one-time code) needs a later CP.
