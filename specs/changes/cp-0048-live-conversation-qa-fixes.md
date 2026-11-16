---
type: Change Proposal
title: CP-0048 Live conversation QA fixes - a person on request, third parties, pounds
description: Three defects found by running 25 real conversations on gpt-4.1-mini - "I want to speak to a human" got a clarifying question, a caller asking about their mum's policy was verified with her details and told her excess, and amounts were spoken in dollars.
status: stable
cp_state: implemented
tags: [qa, escalation, routing, prompts, privacy]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

Live QA of 25 Full-flow conversations on the real model (about $0.40 estimated spend of the owner's $2 budget) found:

1. **A caller who asks for a person does not get one.** At the front desk "I want to speak to a human", "agent please" and "can I talk to someone real" got "Are you calling about your policy, a claim or a quote?"; "get me a manager" got the same. The model-led escalation only works once an agent is open and the model chooses it.
2. **Privacy.** "I'm calling about my mum's policy, not mine. What's her excess?" then her number and date of birth: the agent verified with her details and said "Her excess is £250, and the monthly premium is £61.20", although the third-party rule says never to. A rule in the `never` list is not enough for the model.
3. **Dollars.** "$61.20", "$104 a month" for a UK insurer: the prompt's own example says "$650".

Not fixed here (noted for the owner): a caller's opening details (name, number, date of birth) are not carried through the clarifying question, so the caller repeats them; an obvious opener such as "has my claim CL-70231 been paid?" still gets one clarifying question with embedding routing; the Claims agent escalated "move my Direct Debit date" to a person instead of transferring to Customer Care in one run (a second run answered it itself).

# What changes

* New deterministic **person-request** rule: `escalation.person_match`; the agent's caller rules escalate (`caller_requested`, hand-off line) before any model reply; the front desk routes such a line to the default agent without a clarifying question (`method: person_request`).
* System prompt: pounds sterling (`£`, never `$`), and a ground rule for callers speaking about someone else's policy.

# Affected specs

* [/architecture/escalation.md](/architecture/escalation.md) - ES-13
* [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md) - step 0a, RTE-23
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - pounds, third party

# Acceptance criteria

ES-13, RTE-23 (new). The prompt rules are checked by a prompt-content test and by the live run below (ES-13 and RTE-23 by typed conversations on the fake LLM).

# Tasks

1. Spec edits (done in this CP).
2. `escalation.person_match`, `session._caller_rule`, `supervisor.safety_route` (method), `conversations.front_desk_turn`.
3. Tests in `tests/test_person_request.py` (typed conversations, fake LLM).
4. Re-run the failing live conversations on gpt-4.1-mini within the remaining budget; reseed note for the owner (agent `never` rules come from the seed).

# Risks and rollout

* A false positive escalates a caller who only mentioned a person; the rule needs a request verb and excludes "talk to someone" alone.
* The third-party rule is prompt-level; a determined caller can still try. The groundwork is the same as for every model rule: scored by the `safety` checks, and visible in call review.
* The prompt changes only reach agents on the next call; no reseed is needed for the prompt itself.

# Out of scope

* Carrying opener details across the clarifying question; routing quality with the decision model; Hindi person requests.
