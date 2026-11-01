---
type: Component Spec
title: Learning actions
description: What evaluation and self-learning find becomes a ranked list of actions per agent - a fix that did not hold, an answer only a person can give, a check failing on many calls, drift, a test scenario failing on the live version - each with one next step, closing itself when the finding clears.
status: draft
tags: [architecture, learning, evaluation, insights]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Purpose

[Call scoring](/architecture/call-scoring.md), [test suites](/architecture/test-suites.md) and [self-learning](/architecture/self-learning.md) produce findings; a finding nobody acts on is only a report. A **learning action** is one finding with one next step for a person. Actions are derived, not typed in: every learning run recomputes them, opens what is new and closes what has cleared, so the list is always the current to-do list ([CP-0032](/changes/cp-0032-learning-actions.md)). Proposals (drafted fixes) stay in the learning inbox; actions are everything else that needs a person.

# Kinds

| Kind | Severity | Raised when (per published agent) | Next step | Closes itself when | Key |
|---|---|---|---|---|---|
| `fix_not_holding` | high | Step 0 of the run reopened a fixed cluster ([self-learning](/architecture/self-learning.md)) | Review the new draft, or roll back on the Versions tab | the cluster is `fixed` again or `ignored` | `fix_not_holding:{cluster}` |
| `answer_needed` | high | A ready `missing_knowledge` cluster has no specialist note on any member call and no `human_answer` | Type the answer (**Answer**); it drafts and evaluates a fix | the cluster has a note, an answer or an open proposal, or is no longer ready | `answer_needed:{cluster}` |
| `check_failing` | high for a hard gate, else medium | On the published version's scored real calls of the last 7 days, a check has ≥ 10 decided verdicts and fails on ≥ 20 % | An **uncalibrated judge check**: review the listed calls (up to 10 failing calls without a review of that check); their labels calibrate the judge. Any other check: open the failing calls | the fail rate is below 20 % or under 10 decided; for an uncalibrated judge check also when every listed call has a review of the check | `check_failing:{version}:{check}` |
| `drift` | high | The published version is flagged for drift on a metric (SC-10) | Open Evaluation for the version | the flag clears | `drift:{version}:{metric}` |
| `scenario_failing` | medium | In the latest finished test run of the published version, an enabled scenario passed fewer than all its repeats (*flaky* when some passed) | Open the test run | a later finished run of that version passes it all repeats, or the scenario is disabled or deleted | `scenario_failing:{version}:{scenario}` |

Every action has a `title` (one line, for example "Fix did not hold: Adding a newborn to coverage", "Answer needed: How to extend cover abroad", "Review 10 calls: Did the agent stay grounded?", "Check failing on 35 % of calls: Tool calls succeeded", "Goal met drifted on v3", "Test scenario failing on v3: Claim paid (1/3, flaky)"), a `detail` sentence with the numbers, `evidence` (`{cluster_id?, call_ids?, check_key?, version_id?, scenario_id?, test_run_id?, rate?, decided?, before_per_week?, after_per_week?}`) and an `impact`: the cluster's estimated weekly cost for cluster kinds, otherwise the number of affected calls in the window.

# Lifecycle

* `open` → `done` (a person handled it; note optional), `dismissed` (not useful; note optional) or `resolved` (closed by a run because the finding cleared). `done` and `dismissed` record who and when, and keep the same key from opening again for `learning.snooze_days` ([agent config](/data/agent-config.md)).
* **Answer.** `answer_needed` takes the reviewer's answer (at least 20 characters, the reviewer's name). The answer is stored on the cluster (`human_answer`, `human_answer_by`), the action becomes `done`, and job `draft_and_evaluate` drafts the fix (origin `manual`) and starts its evaluation, so the proposal reaches the inbox with its gate.
* **Derivation** runs per agent as step 7 of every [learning run](/architecture/self-learning.md) (nightly and **Run learning now**), after drafting. For each kind it computes the current findings; for each finding, an open action with the same key is updated (title, detail, evidence, impact), a closed one inside its snooze window is left alone, otherwise a new action opens; an open action whose finding is gone becomes `resolved`. The run's report gets `actions: {opened, resolved, open}` per agent.
* **Ranking.** Open actions sort by severity (high first), then impact (highest first), then age (oldest first).
* Every change publishes `action.updated` (topic `insights`) with the action.

# Fix verification

For each cluster with an approved proposal (`fixed`, or reopened), the API reports `fix`: the resulting version, the approval time, signals per week in the 28 days before the approval and since it (over at least one week), and `held`: `true` once 7 days have passed with no signal since the approval, `false` when the cluster was reopened after it, otherwise `null`.

# Acceptance

- **LA-01** — Given a cluster reopened by step 0 of a run, then one open `fix_not_holding` action with key `fix_not_holding:{cluster}` and high severity exists; when a later proposal for the cluster is approved and the next run finishes, the action is `resolved`.
- **LA-02** — Given an open `answer_needed` action, when `POST /api/actions/{id}/answer` sends an answer of 25 characters, then the cluster's `human_answer` is that text, the action is `done`, and a proposal whose drafting evidence contains the answer reaches `ready` with an evaluation; an answer of 10 characters returns 422 `answer_too_short`.
- **LA-03** — Given a published version with 12 scored real calls in the last 7 days of which 4 fail `tools.succeeded`, when a run finishes, then an open `check_failing` action exists for that check with medium severity, rate 0.33 and the 4 call ids; when a later run sees 1 failure in 12, it is `resolved`.
- **LA-04** — Given an uncalibrated judge check failing on 3 of 10 calls, then the action's title starts "Review" and it lists those 3 calls; when each has a review of that check and a run finishes, it is `resolved`.
- **LA-05** — Given a version flagged for drift on `goal_met`, when a run finishes, then an open `drift` action exists with high severity; it is `resolved` after a run in which the flag is gone.
- **LA-06** — Given the latest finished test run of the published version in which an enabled scenario passed 1 of 3, then an open `scenario_failing` action marked flaky exists; after a later run of that version passes it 3 of 3, it is `resolved`.
- **LA-07** — Given an open action that is dismissed, when the next run finds the same finding, then no new action opens for its key until `learning.snooze_days` have passed.
- **LA-08** — Given open actions of high and medium severity, then `GET /api/insights/actions` lists the high ones first and, within a severity, the higher impact first.
- **LA-09** — Given a fixed cluster approved 10 days ago with 6 signals in the 28 days before and none since, then its `fix` reports `before_per_week` 1.5, `after_per_week` 0 and `held: true`.
