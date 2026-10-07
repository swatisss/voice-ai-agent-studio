---
type: Component Spec
title: Call modes
description: Inbound, outbound and internal agent modes - call context, outbound targets and opening, identity rules per mode, mode prompts, and how calls record their direction.
status: stable
tags: [architecture, outbound, internal]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Modes

An agent has a `mode` in its config ([/data/agent-config.md](/data/agent-config.md)); every call records it as `direction`.

| Mode | Who speaks first | Audience | Identity |
|---|---|---|---|
| `inbound` (default) | the agent, with the persona's greeting and disclosure | a customer who called in | caller verifies with member ID + date of birth before account detail |
| `outbound` | the agent, with the persona's **opening** | a customer the agent is calling | the agent knows whom it is calling, but the callee must still confirm their date of birth before any account detail |
| `internal` | the agent, with the persona's greeting and disclosure | Evergreen staff (assumed authenticated by the surrounding channel) | no member verification; the agent never discloses member data |

"Speaks first" holds for every channel: in a text chat the first utterance is shown on start; in a voice call it is **spoken** as soon as the pipeline is ready, without the caller saying anything ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), VO-07).

The mode selects a mode prompt ([/prompts/mode-inbound.md](/prompts/mode-inbound.md), [/prompts/mode-outbound.md](/prompts/mode-outbound.md), [/prompts/mode-internal.md](/prompts/mode-internal.md)) that is inserted into the system prompt ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md)) as `mode_instructions`.

# Outbound calls

* **Targets.** The agent config holds `outbound.targets_url`, a business-API URL (relative URLs run in-process) that returns `{"targets": [{"member_ref", "first_name", "summary", "context": {...}}]}`. `GET /api/outbound/targets?agent_id=` returns that list for the UI; 409 `not_outbound` for an agent that is not outbound.
* **Placing a call.** `POST /api/calls` for an outbound agent requires `context.member_ref`; it must match a target (else 422 `unknown_target`). The stored call context is the target's `context` plus `member_ref`, `first_name` and `member_id` (digits).
* **Opening.** The first agent utterance is the persona `opening` with `{placeholders}` filled from the call context (missing placeholders become empty); if the persona has no opening, a default is used: "Hello, may I speak with {first_name}? This is {persona name} calling from {brand}." followed by the persona disclosure. The inbound greeting is not used.
* **Prompt context.** The system prompt receives the call context as `call_context` (one `- key: value` line each; the member ID is labelled *never read aloud*).
* **Identity.** The call starts **unverified**. Tools marked `requires_verification` stay blocked until `verify_member` succeeds, exactly as for inbound calls ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)); the context never marks the call verified.
* **Handoff.** The outbound agent's `handoff_message` offers a callback or a specialist; escalation, packets and learning work as for inbound calls.

# Internal calls

The internal prompt tells the agent its audience is staff, to search internal knowledge before answering, to cite the article title, to say when a procedure is not documented, and to refuse requests for individual member data. Tools without `requires_verification` run normally; the verification gate does not apply because internal tools take no member context.

# Direction in data and UI

`calls.direction` (`inbound` · `outbound` · `internal`) is set at call creation from the agent's mode, returned in call summaries, and filterable in `GET /api/calls?direction=`. The Calls explorer shows it as a badge.

# Acceptance

- **OB-01** — Given an outbound agent, when `POST /api/calls` has no `context.member_ref` or an unknown one, then the response is 422 `unknown_target`; with a listed target the call is created and its context contains `first_name`, `member_ref` and the target's context.
- **OB-02** — Given an outbound call, when it starts, then the first agent utterance is the persona opening with the callee's first name filled in (not the inbound greeting) and the call's `direction` is `outbound`.
- **OB-03** — Given an outbound call whose callee has not verified, when the model calls a tool marked `requires_verification`, then no business-API request is made and the result is `identity_not_verified`; after `verify_member` succeeds the tool runs.
- **OB-04** — Given an internal agent, when a turn runs, then the system prompt contains the internal-audience instructions, and a tool without `requires_verification` executes without verification.
- **OB-05** — Given an outbound agent, when `GET /api/outbound/targets?agent_id=` is called, then it returns the targets from the agent's `targets_url`; for an inbound agent it returns 409 `not_outbound`.
- **OB-06** — Given calls of each mode, when listed or opened, then each carries its `direction`, and `GET /api/calls?direction=outbound` returns only outbound calls.
