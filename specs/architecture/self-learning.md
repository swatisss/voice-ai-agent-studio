---
type: Component Spec
title: Self-learning
description: A nightly job turns each agent's day of calls into typed config change proposals - knowledge, tools, skills, rules - proves each one offline against the current version, and queues it for a human; agents never change themselves.
status: draft
tags: [architecture, learning, evaluation, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-31T00:00:00Z" }
---

# Purpose

Agents improve from their own calls without ever changing themselves. Every night the platform reviews what each agent did, finds the gaps that keep recurring, drafts a change to the agent's **declarative config** (a knowledge article or edit, a tool to attach, a skill with its tool, a policy rule), proves it offline against the current version, and leaves it in the **learning inbox**. A human approves, edits or rejects it; only an approval publishes a new version ([ADR-0011](/decisions/adr-0011-evaluation-and-self-learning.md), [healthcare compliance](/product/healthcare-compliance.md) rule 8).

It extends [fleet learning](/architecture/fleet-learning.md) (analysis, clustering, drafting, approval) and reuses [call scoring](/architecture/call-scoring.md) for signals and [test suites](/architecture/test-suites.md) for the gate.

# Nightly run

The job worker starts `nightly_learning` once a day per tenant after `LEARNING_NIGHTLY_HOUR_UTC` (default 2, i.e. 02:00 UTC), dedupe `nightly_learning:{tenant}:{date}` ([/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)); `POST /api/learning/run` starts one now (409 `run_in_progress` while one runs). Each run is a `learning_runs` row with a per-agent summary. For every published agent with `learning.nightly` on ([/data/agent-config.md](/data/agent-config.md)):

1. **Signals.** Real calls (not simulations, not seeded) that ended since the previous finished run (at most 7 days back) and carry an **external signal**:

   | Signal | From |
   |---|---|
   | escalated | the call (already a learning candidate) |
   | thumbs down | caller feedback (already a learning candidate) |
   | knowledge search with no answer | the call's `search_knowledge` results |
   | tool error | scorecard measure `tool_errors` > 0 |
   | hard fail | a code-decided hard-gate check failed |
   | calibrated judge fail | a judge check failed whose check is *calibrated* for the agent (≥ 20 reviews, ≥ 85 % agreement) |

   Uncalibrated judge verdicts are never signals: the loop learns only from what humans, callers, the business systems or the event log say.
2. **Re-analysis.** A call with a signal whose analysis has root cause `none` is analysed again with its signals (`analyze_call`, dedupe `analyze_call:{id}:signals`). The [call analysis prompt](/prompts/call-analysis.md) treats signals like a thumbs down: root cause never `none`, a non-empty gap summary, so the call joins a cluster (a **quality candidate**).
3. **Readiness.** A cluster's `signal_count` counts escalations, thumbs-down calls and quality candidates in the last 28 days ([fleet learning](/architecture/fleet-learning.md) §3). Clusters snoozed until a later date are skipped.
4. **Drafting.** Ready clusters without an open proposal, highest estimated weekly cost first, up to `learning.max_proposals_per_night` (default 3): `draft_fix` with origin `nightly`. Each proposal also gets up to 2 **derived scenarios** from its evidence calls (the caller goal, the member profile of a verified caller, expected `resolved`, persona `calm`).
5. **Gate.** Each new proposal is evaluated (below). Whatever the result, it waits in the inbox; nothing is approved or published by the run.
6. **Report.** The run stores per agent: calls reviewed, signals by kind, re-analysed calls, ready clusters, proposals drafted and how many passed the gate; publishes `learning.run.finished` (topic `insights`).

# Proposal kinds

| Kind | When | Payload | On approval |
|---|---|---|---|
| `knowledge_article` | missing knowledge, no article covers it | `{article: {title, content_markdown}}` | the draft doc becomes active and is attached |
| `knowledge_edit` | missing knowledge, an attached article covers the topic but lacks the answer | `{doc_id, article: {title, content_markdown}}` (the full revised article) | a new active doc replaces `doc_id` in the agent's documents; the old doc is archived |
| `tool_attach` | missing skill, an existing tenant tool fits but is not attached | `{tool_name}` | the tool is attached |
| `skill` | missing skill, a procedure (and maybe a catalog tool) is needed | as today | as today |
| `policy_rule` | agent error | as today | as today |

Every payload may add `scenarios` (the derived scenarios). On approval they join the agent's test suite, enabled.

# Gate

A proposal evaluation ([evaluation](/architecture/evaluation.md)) runs every case on **both arms** (baseline = published version, candidate = baseline with the proposal applied in memory), scores every simulated call ([call scoring](/architecture/call-scoring.md), judge on), and decides:

| Case set | Content | Repeats |
|---|---|---|
| cluster | up to `EV_MAX_CLUSTER_CASES` evidence calls used for drafting | 1 |
| held-out | up to 4 other member calls of the cluster, never shown to the drafter | 1 |
| derived | the proposal's derived scenarios | 1 |
| regression | the agent's enabled test scenarios ([test suites](/architecture/test-suites.md)) | `learning.regression_repeats` (default 3) |

A derived scenario that **passes on the baseline** is dropped from the proposal (it does not show the gap). The gate **passes** when all of:

1. **Lift** — candidate passes on cluster + held-out cases exceed the baseline's by at least one, and the candidate passes at least half of the held-out cases when there are any.
2. **No regression** — no test scenario that passed every repeat on the baseline passes fewer than `repeats − 1` on the candidate.
3. **No new hard fails** — the candidate has no hard-failed scorecard on a case where the baseline had none.
4. **No slowdown** — the candidate's p95 response time over all its simulated calls is at most 1.2 × the baseline's.

The summary keeps each part with its numbers and a `gate: {passed, reasons}`; the reasons are shown to the reviewer ("2 test scenarios regressed: Claim paid 3/3 → 1/3").

# Review

* The **learning inbox** ([/ui/insights.md](/ui/insights.md)) lists proposals in `ready` that no one has decided, newest first: origin (*Nightly* / *Manual*), kind, title, rationale, the change itself (article diff for an edit), the gate with its reasons, evidence calls, held-out results and derived scenarios.
* **Approve & publish** is allowed when the gate passed, or with `force` and a note ([fleet learning](/architecture/fleet-learning.md) §5). It applies the change, adds the derived scenarios, publishes a version (`change_note` "Fix: …", `source_proposal_id`), and — with `evaluation.test_on_publish` — starts a test run of the new version.
* **Edit** returns the proposal to `draft`; re-evaluating it runs the gate again.
* **Reject** needs a note; the cluster is snoozed for `learning.snooze_days` (default 7) so the next nights do not draft the same fix again.

# Guardrails

1. The runtime has no path to change an agent's config; only an approval (a human, with a name) creates a version.
2. Learning uses external signals only (table above); uncalibrated judge verdicts never start or gate anything.
3. At most `learning.max_proposals_per_night` proposals per agent per night; rejected clusters are snoozed.
4. Drafts never contain member-specific data or medical advice ([/prompts/fix-draft.md](/prompts/fix-draft.md)); agent-written member memory is never evidence.
5. Held-out cases are never shown to the drafter, so a fix cannot be fitted to the cases that judge it.
6. A rollback is publishing an earlier version's config again (out of the box: the Versions tab).

# Acceptance

- **SL-01** — Given the worker idle after 02:00 UTC, then one `nightly_learning` job per tenant runs per day; a second start the same day is deduplicated, and `POST /api/learning/run` while one runs returns 409 `run_in_progress`.
- **SL-02** — Given a resolved call with a no-answer knowledge search and analysis root cause `none`, when the nightly run reviews it, then it is re-analysed once with its signals, gets a root cause other than `none` and joins a cluster.
- **SL-03** — Given a resolved call whose only failed check is an uncalibrated judge check, then the nightly run does not re-analyse it; given the same check calibrated, it does.
- **SL-04** — Given four ready clusters for an agent with `max_proposals_per_night: 3`, then the run drafts three proposals with origin `nightly`, for the three highest estimated weekly costs.
- **SL-05** — Given a cluster whose proposal was rejected, then no nightly run drafts for it until its snooze date has passed.
- **SL-06** — Given a `knowledge_edit` proposal for an attached doc, when approved, then the new version lists a new active doc instead of the old one and the old doc is archived.
- **SL-07** — Given a `tool_attach` proposal, when approved, then the new version's snapshot contains that tool and no new tool row was created.
- **SL-08** — Given a proposal evaluation, then held-out cases are cluster members not in the drafting evidence, the drafter's prompt never contained them, and every case ran on both arms.
- **SL-09** — Given a derived scenario that passes on the baseline, then it is dropped from the proposal; a derived scenario kept by an approved proposal is an enabled test scenario of the agent afterwards.
- **SL-10** — Given a candidate on which a test scenario passing 3/3 on the baseline passes 1/3, then the gate fails with a reason naming the scenario, and approval without `force` and a note returns 409 `evaluation_gate`.
- **SL-11** — Given a nightly run, then no agent version is created, no agent draft changes and no proposal is approved, whatever the gate results.
- **SL-12** — Given a finished nightly run, then `learning.run.finished` is published and `GET /api/learning/runs` returns its per-agent summary with signals by kind and proposals drafted and passed.
