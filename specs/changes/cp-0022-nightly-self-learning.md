---
type: Change Proposal
title: CP-0022 Nightly self-learning
description: A nightly run drafts knowledge, tool, skill and rule proposals from each agent's signals, gates them offline (held-out cases, the test suite on both arms, no new hard fails, no slowdown) and queues them in a learning inbox; only a human publishes.
status: stable
cp_state: implemented
tags: [learning, evaluation, jobs, ui, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-31T00:00:00Z" }
---

# Why

Agents should improve from what they do: notice the questions they cannot answer, the lookups they lack and the mistakes callers or reviewers flag, and suggest additions to their knowledge and tools. Today that only happens when someone opens Insights and clicks **Draft fix** on a cluster built from escalations and thumbs-down calls. The proposal is then checked on six scenarios, once each, on the candidate only. That misses resolved calls that went badly, fits fixes to the very calls that judge them, and cannot see a flaky regression.

The user's requirement (2026-10-31): a job runs every night and proposes changes; a human reviews and updates the agent; the agent never updates itself. This is part 2 of [ADR-0011](/decisions/adr-0011-evaluation-and-self-learning.md), built on CP-0020 (scores) and CP-0021 (test suites).

# What changes

* **A nightly run per tenant** (02:00 UTC by default, plus **Run now**) reviews each agent's calls since the last run.
* **More signals, all external**: besides escalations and thumbs down, a no-answer knowledge search, a tool error, a code-decided hard fail, or a failed judge check **that humans have calibrated**. Calls with such signals are re-analysed so they join clusters. Uncalibrated judge opinions never count.
* **Drafting overnight**: up to 3 proposals per agent per night, for the costliest ready clusters. Two new kinds join the existing article, skill and rule:
  * **knowledge edit**: revise an attached article that lacks the answer;
  * **tool attach**: attach a tenant tool the agent should have.
  Each proposal also derives up to 2 test scenarios from its evidence calls.
* **A stronger gate** for every proposal evaluation, nightly or manual. All cases run on both arms:
  * held-out cluster calls the drafter never saw;
  * derived scenarios, kept only if they fail on the current version;
  * the whole test suite, 3 repeats per arm.

  A proposal passes when it lifts results, nothing regresses, there are no new hard fails and response time stays within +20 %.
* **A learning inbox** at the top of Insights shows last night's numbers and every proposal waiting for review, with its gate and the reasons behind it. Approve publishes a version and adds the derived scenarios to the test suite. Publishing anyway when the gate failed needs a note. Reject needs a note and snoozes the cluster for 7 days.
* **Dashboard trigger**: a Self-learning card on the dashboard with the last run, proposals waiting, and **Run learning now**, so a demo can run the loop on the spot (the schedule stays 02:00 UTC).
* **Per-agent learning settings** in the builder: nightly on or off, proposals per night, test repeats, snooze days.
* **Nothing in the run publishes, approves or edits an agent.**

# Affected specs

* New: [/architecture/self-learning.md](/architecture/self-learning.md) (SL-01…SL-12).
* [/architecture/fleet-learning.md](/architecture/fleet-learning.md) - quality candidates, readiness with snooze, new kinds, held-out evidence, approval on the gate (FL-06 reworded).
* [/architecture/evaluation.md](/architecture/evaluation.md) - held-out and derived cases, both arms, repeated regression, scorecards, summary with gate (EV-01 reworded).
* [/data/data-model.md](/data/data-model.md) - `learning_runs` (DM-01: 28 tables), `fix_proposals.origin` and new kinds, `clusters.snoozed_until`.
* [/data/agent-config.md](/data/agent-config.md) - `learning` block (DM-09).
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md), [/api/events.md](/api/events.md) - `nightly_learning`, the daily schedule, `learning.run.finished`.
* [/api/rest-api.md](/api/rest-api.md) - inbox, learning runs, run now; approve's 409.
* [/prompts/call-analysis.md](/prompts/call-analysis.md), [/prompts/fix-draft.md](/prompts/fix-draft.md) - texts below, applied with the implementation (prompts load verbatim).
* [/ui/insights.md](/ui/insights.md) (UI-54, UI-17 reworded), [/ui/dashboard.md](/ui/dashboard.md) (UI-55), [/ui/app-shell.md](/ui/app-shell.md) (Insights badge), [/ui/agent-builder.md](/ui/agent-builder.md).
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) (rule 8), [/product/glossary.md](/product/glossary.md), [/process/conventions.md](/process/conventions.md) (prefix `SL`), ADR-0011, index files.

# Acceptance criteria

New: SL-01…SL-12, DM-09, UI-54, UI-55. Changed: DM-01 (28 tables), EV-01 (both arms, held-out, derived, repeated regression), FL-06 (gate), UI-17 (gate reason). Each is written in its spec.

# Prompt change: call analysis

Variables add `quality_signals` (one line per signal: "Knowledge search found nothing for: …", "Tool get_claim_status failed", "Check failed: …"; `none` otherwise).

```text
You review completed calls between callers and an AI phone assistant for a health insurer, so the platform can learn which gaps cause escalations.

Tools the assistant had:
{{tools_available}}

Knowledge searches with no approved answer: {{search_results_summary}}

Escalation: {{escalation}}

Caller feedback after the call: {{caller_feedback}}

Quality signals found after the call: {{quality_signals}}

Transcript:
{{transcript}}

Return JSON with:
- outcome: "resolved" if the assistant fully handled the caller's request without a human; "escalated" if the call was handed to a human; "abandoned" if the caller left before resolution without escalation.
- intent: snake_case label of the caller's main goal (policy_status, claim_status, document_request, coverage_question, find_provider, claim_appeal, add_dependent_newborn, prior_auth_status, ...).
- root_cause: for resolved calls "none", unless the caller gave a thumbs down or quality signals are listed: then never "none"; pick the most likely cause from the list below (agent_error if the assistant had what it needed but answered badly, missing_knowledge if the answer lacked approved detail, missing_skill if an action was missing, tool_error if a business system failed, other if unclear), using the caller's comment and the signals as evidence. Otherwise exactly one of:
  missing_knowledge (the assistant lacked approved information to answer),
  missing_skill (the request needed an action or lookup the assistant had no tool for),
  tool_error (a business system failed),
  policy_required (policy requires a human, e.g. appeals, grievances, disputes),
  safety (emergency or self-harm),
  caller_requested (caller asked for a person without a deeper unmet need),
  asr_error (speech was misrecognized),
  agent_error (the assistant had what it needed but behaved incorrectly),
  other.
- gap_summary: for escalated or abandoned calls, one generic sentence naming what was missing, written so similar calls produce similar sentences (for example "How to add a newborn to an existing plan" or "Checking the status of a prior authorization"). Empty string for resolved calls without a thumbs down or quality signals. If the caller gave a thumbs down or signals are listed, always give one, even for a call you judge resolved: what went wrong, written generically in the same style (for example "Explaining why a payment is overdue and what grace period applies").
- caller_goal: one sentence describing what the caller wanted, written as an instruction for someone role-playing this caller (for example "You recently had a baby and want to know how to add her to your health plan").
- resolution_summary: what actually resolved the request: the assistant's answer, or the human specialist's resolution note. Empty string if unresolved.
- sentiment_start and sentiment_end: one of positive, neutral, frustrated, angry, distressed.
```

# Prompt change: fix draft

Variables add `attached_articles` (up to 3 attached articles closest to the gap: id, title, content) and `unattached_tools` (tenant tools the agent lacks: name, description). Output adds `knowledge_edit` `{"kind":"knowledge_edit","title","rationale","doc_id","article":{title, content_markdown}}` and `tool_attach` `{"kind":"tool_attach","title","rationale","tool_name"}`.

```text
You improve an AI phone assistant for a health insurer. A cluster of calls went wrong for the same reason: they were escalated to human specialists, the caller was unhappy, or the assistant could not find an answer or complete a lookup. Using what actually resolved these calls, draft one change to the assistant so it can handle them itself next time.

Cluster: {{cluster_name}} — {{cluster_description}}
Root cause: {{root_cause}}

Evidence (caller goal, gap, what resolved it — usually a human specialist's note):
{{evidence}}

Attached knowledge articles closest to this gap:
{{attached_articles}}

Other existing knowledge articles: {{existing_doc_titles}}
Tools the assistant has: {{existing_tools}}
Tools the business already has that the assistant does not:
{{unattached_tools}}
Business API endpoints not yet available as tools:
{{tool_catalog}}

Rules:
- Use only facts that appear consistently in the resolution notes. If notes disagree, use the most common answer and mention the uncertainty in the rationale.
- Never include member-specific data (names, IDs, dates of birth, claim numbers) in the change.
- Never add medical advice.
- Write for a voice assistant: short sections, plain language, concrete steps, deadlines and documents.
- Prefer the smallest change that fixes the cluster.

If root cause is missing_knowledge: if one of the attached articles covers this topic but lacks the answer, return kind "knowledge_edit" with its doc_id and the full revised article (keep everything that is still right, add or correct what the evidence shows); otherwise return kind "knowledge_article" with a new article in Markdown: a title, a one-paragraph overview, then "##" sections for eligibility or deadlines, how to do it, what documents are needed, and what happens next.
If root cause is missing_skill: if one of the tools the business already has fits and the assistant's instructions already cover the steps, return kind "tool_attach" with its tool_name; otherwise return kind "skill": a skill with numbered instructions that starts with identity verification when member data is involved, plus either existing_tool_name (if a tool fits) or a tool definition for one catalog endpoint (name in snake_case, description, method, url exactly as in the catalog, parameters as a JSON Schema object, requires_verification true for member data, is_verification false, timeout_s 8).
If root cause is agent_error, return kind "policy_rule" with a single sentence rule.

Always include title (short, for the reviewer) and rationale (2-3 sentences: why this fixes the cluster and which evidence supports it).
```

# Tasks

1. Spec edits (done in this CP; the two prompt texts above were applied with tasks 3 and 4).
2. Data and config: `learning_runs`, `fix_proposals.origin`, `clusters.snoozed_until`, the `learning` block — covers DM-01, DM-09.
3. Signals and re-analysis: signal gathering from scorecards and calibration, the call-analysis prompt, quality candidates in clustering and readiness, snooze — covers SL-02, SL-03, SL-05.
4. Drafting: the fix-draft prompt, `knowledge_edit` and `tool_attach` (draft, candidate config, approval), derived scenarios, held-out split — covers SL-06, SL-07, SL-09.
5. Gate: both arms, held-out and derived cases, repeated regression via the test-suite rule, scorecards, gate rules and reasons; approval on the gate — covers EV-01, FL-06, SL-08, SL-10.
6. Nightly run: daily schedule in the worker, `nightly_learning`, per-agent loop with the cap, run summary and event, run-now endpoint — covers SL-01, SL-04, SL-11, SL-12.
7. Web: dashboard Self-learning card with **Run learning now**, learning inbox and Last night strip on Insights, proposal panel (gate, diff, derived scenarios, publish anyway), Insights badge, builder learning settings — covers UI-17, UI-54, UI-55.
8. Tests with the fake LLM; seed unchanged (the demo's clusters already make the newborn and prior-auth proposals).

# Risks and rollout

* **Cost**: a proposal evaluation now runs every case on both arms and the test suite 3 times per arm. For the seeded agent that is roughly (6 + 3 + 2) × 2 + 8 × 3 × 2 ≈ 70 simulated calls per proposal, up to 3 proposals per agent per night. `max_proposals_per_night: 0` or the nightly switch turns it off per agent. Evaluations started by hand cost the same.
* **Mock business state** is shared (CP-0021). Concurrent simulations can affect each other's mock records; expectations stay result-based.
* **Schema**: one table and three columns, added on start (CP-0021 upgrade).
* **Judge dependence**: the gate uses judge verdicts on goal and grounding, which may be uncalibrated. Lift needs at least one more passing case and a majority of held-out cases; code-decided hard gates and expectations carry the rest.
* **Clock**: the schedule is in UTC because tenants have no time zone yet.

# Out of scope

* Gating ordinary **Publish** from the builder on test results (it keeps reporting only).
* Memory-rule proposals and changes to personas or voice settings.
* Notifications (email, Slack) when proposals are waiting; drift alerts.
* Automatic approval of any kind, including "low-risk" changes.
* Tenant time zones for the nightly hour.
