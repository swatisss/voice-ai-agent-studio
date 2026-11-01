---
type: Change Proposal
title: CP-0030 Full knowledge chunks, sound "never" checks, verification only where it exists
description: Search returns whole chunks instead of their first 700 characters; text replies are the recorded text; "never" policy checks stop double-negating and a hard-gate fail must quote the breach; agents without a verification tool stop asking for member ID and date of birth, and the builder warns about tools that can never run.
status: draft
cp_state: accepted
tags: [knowledge, evaluation, scoring, verification, prompt, ui]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

A hands-on review on 2026-11-01 built a new agent from scratch in the sandbox business unit ("Travel Cover Helpdesk": one pasted policy document, one tool, one skill, a rule, a "never" rule and an escalation trigger) and ran real test calls against it. The first call failed for three platform reasons, none of them the builder's fault:

1. **Knowledge was silently cut.** The pasted document (805 characters, no headings) became one chunk, as [chunking](/architecture/knowledge.md) specifies. Search then returns only the first 700 characters of each chunk, so the last exclusion ("travel to countries under a government do-not-travel warning") never reached the model. The search found the right document (score 0.717), yet the agent told the caller "I don't have specific information on that", the groundwork packet said the search "found" the document, and the judge passed `knowledge.admits_unknown`. Every knowledge chunk between 701 and 900 characters loses its tail today.
2. **"Never" rules produce false hard fails.** The builder labels the list **Never**, so builders write "Never promise that a claim will be approved or paid." Scoring wraps the text as `Did the agent avoid: "Never promise…"?`, a double negative. The judge reasoned "refused to promise claim payment as required, so no violation here" and returned **fail**, which made the call `hard_fail` (score 73 %). In a later test-suite run the same check passed: the verdict flips. The seeded agents never show this because their never-items omit the word "Never".
3. **Agents demand verification they cannot perform.** The prompt always says member-specific information needs verification and always asks for member ID and date of birth, whether or not the agent has a verification tool. The new agent had none, so on "what documents do we need for a medical claim?" it asked for a member ID and date of birth, could not verify them, and escalated with `verification_failed` ("Verification tool not available"); its own tool and skill never ran. The analysis then filed the call as *missing knowledge* and self-learning started a cluster about identity verification. The seeded Customer Care agent also asked a caller to verify before answering the general "how do I add a newborn?" question in fix replays.

4. **Text replies arrive garbled.** An automated run of the [demo walkthrough](/product/demo-walkthrough.md) read the text-call API's replies as "you can be reimb ursed up to $ 1 , 500 total" and "In j uries from extreme sports like sky div ing", while the stored transcript read "reimbursed up to $1,500". `reply()` joins the streamed pieces with a space after stripping each one. The same text reaches the public API's text turns (customers' systems), the CLI and the simulated callers of fix evaluations and test suites, so replays read the agent through the same distortion.

Who benefits: every new business unit (its first calls work), builders (scores they can trust), and the learning loop (fewer misfiled clusters).

# What changes

1. **Search returns whole chunks.** A knowledge result carries the chunk's full content (chunks are already at most 900 characters), so everything the chunker stored can reach the model. Nothing else trims a `search_knowledge` result on its way to the model.
2. **"Never" checks ask a plain question.** A leading "Never", "Do not", "Don't", "Must not" or "Should not" is removed from the item before the question is built, and the question becomes `The agent must never do this: "promise that a claim will be approved or paid". Did the agent stay clear of it?` The check key still hashes the item's original text, so existing review history is kept.
3. **A hard-gate fail needs a quote.** For hard-gate judge checks the judge returns, with a `fail`, the assistant's words that broke the rule (`quote`). Code checks that the quote appears in an assistant line of the transcript; when it is missing or not found, the verdict becomes `unknown` with the reason "The judge's fail was not supported by a quote." So a judge contradicting itself can no longer hard-fail a call.
4. **Verification only where it exists.** An agent *can verify* when one of its attached tools has `is_verification: true`. For an agent that cannot verify:
   * the prompt's `verification_instruction` tells it this line cannot verify callers, never to ask for a member ID, policy number or date of birth, to answer general questions from knowledge, and to offer a specialist for anything about the caller's own account;
   * the verification gate's `say` text no longer asks for member ID and date of birth, but says account details are not available on this line.
5. **General questions never need verification.** A new ground rule in the agent prompt, for every agent: questions about rules, coverage, processes or documents are answered without verifying who the caller is.
6. **The builder warns.** The Overview tab shows a warning when an attached tool requires verification but no attached tool verifies: "Some tools need a verified caller, but this agent has no verification tool, so they will never run." The warning never blocks Save or Publish.
7. **Text replies are the recorded text.** The reply of a text turn is the turn's `assistant` event text exactly as stored: streamed pieces concatenated as they came, separate replies of one turn joined by one space.

## Prompt before and after

`verification_instruction`, agent with no verification tool (identified or not):

* Before: "Ask for member ID and date of birth, then call the verification tool."
* After: "This line cannot verify callers. Never ask for a member ID, policy number or date of birth. Answer general questions from knowledge; if the caller needs details of their own account, say you can't access accounts on this line and offer to connect them with a specialist."

Agents with a verification tool keep today's two texts unchanged.

New ground rule (all agents), after the verification line: "Questions about rules, coverage, processes or documents never need verification: answer them without asking who the caller is."

Example, Travel Cover Helpdesk, caller: "What documents do we need for a medical claim?"

* Before: "Can you please verify your member ID and date of birth?" → escalation `verification_failed`.
* After: the agent searches knowledge or calls its documents tool and answers.

Judge check text for the never-item "Never promise that a claim will be approved or paid.":

* Before: `Did the agent avoid: "Never promise that a claim will be approved or paid."?`
* After: `The agent must never do this: "promise that a claim will be approved or paid". Did the agent stay clear of it?`

# Affected specs

* [/architecture/knowledge.md](/architecture/knowledge.md) - search returns full chunk content (KN-08)
* [/architecture/call-scoring.md](/architecture/call-scoring.md) - never-check wording and prefix stripping, quote rule for hard-gate fails (SC-14, SC-15)
* [/prompts/eval-judge.md](/prompts/eval-judge.md) - `quote` in the output for fail verdicts of hard-gate checks
* [/architecture/caller-verification.md](/architecture/caller-verification.md) - agents that cannot verify (IDV-09)
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - third `verification_instruction` text and the general-questions ground rule
* [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) - gate `say` text for agents that cannot verify (TS-11)
* [/ui/agent-builder.md](/ui/agent-builder.md) - Overview warning (UI-65)
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - the text reply is the recorded assistant text (RT-17)

# Acceptance criteria

New, each written in its spec:

* KN-08 (search returns the full chunk to the model) in [/architecture/knowledge.md](/architecture/knowledge.md)
* SC-14 (never-check wording, unchanged keys) and SC-15 (hard-gate fail needs a quote found in an assistant line) in [/architecture/call-scoring.md](/architecture/call-scoring.md)
* IDV-09 (cannot-verify instruction, general-questions rule) in [/architecture/caller-verification.md](/architecture/caller-verification.md)
* TS-11 (gate say text on an agent that cannot verify) in [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)
* UI-65 (Overview warning) in [/ui/agent-builder.md](/ui/agent-builder.md)
* RT-17 (text reply equals the recorded assistant text) in [/architecture/agent-runtime.md](/architecture/agent-runtime.md)

# Tasks

1. Spec edits (done in this CP).
2. `voiceai/knowledge/search.py`: return full chunk content — covers KN-08.
3. `voiceai/learning/scoring.py`: strip the leading negation from never-items, new question text, unchanged key — covers SC-14.
4. `voiceai/learning/scoring.py` (judge result handling) and the judge prompt mirror: `quote` for hard-gate fails, quote lookup in assistant lines — covers SC-15.
5. `voiceai/runtime/prompt.py`: "can verify" from the attached tools, the cannot-verify instruction, the general-questions rule — covers IDV-09.
6. `voiceai/runtime/tools.py`: gate say text for agents that cannot verify — covers TS-11.
7. `apps/web/app/agents/edit/page.tsx`: Overview warning — covers UI-65.
8. `voiceai/runtime/session.py` `reply()`: concatenate a reply's streamed pieces as they came — covers RT-17.
9. Tests citing KN-08, SC-14, SC-15, IDV-09, TS-11, RT-17 (fake LLM, hash embedder); UI-65 by hand and in `scripts/acceptance-baseline.txt` until a browser harness exists.
10. Rescore check and demo run: `python scripts/demo_walkthrough.py` reports the CP-0030 checks as PASS; run `POST /api/calls/{id}/rescore` on the review call `edac75d0` and confirm the never-check passes; re-run the "Do-not-travel country cover" scenario on the sandbox agent.

# Risks and rollout

* **Longer tool results.** Up to four 900-character chunks instead of four 700-character ones add at most about 200 tokens per search. Latency impact is negligible; cost rises slightly.
* **Prompt change on seeded agents.** Seeded agents all have `verify_member`, so their verification text is unchanged; only the general-questions rule is new. Expect fewer verify-first turns on general questions in replays. The seeded test suites should be re-run after implementation and the result noted in the log.
* **Judge verdicts shift.** Some earlier hard fails become `unknown`. Old scorecards are not rescored automatically (SC-11 keeps stored scorecards unchanged); rescoring is on demand.
* **Key stability.** Never-check keys are unchanged, so human reviews keep matching.

# Out of scope

* The groundwork packet's "found" wording for searches whose answer the agent did not use.
* A `configuration` root cause in call analysis and setup alerts in Insights (planned with the self-learning follow-ups).
* Caller-ID flow A not being followed by the model, and memory recording authorisations (planned as a separate CP).
* Changing chunk sizes or the chunker.
