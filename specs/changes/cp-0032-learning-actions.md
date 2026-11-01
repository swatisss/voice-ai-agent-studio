---
type: Change Proposal
title: CP-0032 Learning actions - evaluation and learning findings become work
description: Every learning run turns what evaluation and learning find into a ranked list of actions (a fix that did not hold, an answer only a person can give, a check failing on many calls, drift, a test scenario failing on the live version); each action names its next step, closes itself when the condition clears, and knowledge fixes are drafted only from human answers.
status: draft
cp_state: accepted
tags: [learning, evaluation, insights, ui, api]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

The self-learning review ([How self-learning should work](/architecture/self-learning-target.md), roadmap R15, R18, R20) found that evaluation is observed but not acted on, and that learning has two blind spots:

* **Evaluation drives nothing (R20).** Drift flags, checks failing on many calls and test scenarios failing on the live version are shown on the Evaluation page and create no work. A judge check counts as a learning signal only once it is calibrated (20 reviews at 85 % agreement, SC-09), and nothing asks anyone to review, so calibration rarely happens.
* **Nobody checks whether a fix worked (R15).** An approved fix marks its cluster `fixed`; later calls with the same gap still join it, but readiness needs `open`, so a fix that did not hold goes silent.
* **Knowledge can be learned from the AI itself (R18).** When an evidence call has no specialist note, the drafter is shown the analysis's own `resolution_summary` as the specialist's answer, and clusters built from quality signals never have a note.

Research (2026-11-01): Intercom Fin's *Optimize* and Decagon's *Suggestions* turn unresolved conversations into typed, impact-ranked suggestions drafted from **human** resolutions, which a team accepts, edits or rejects and which do not reappear once decided ([Intercom](https://fin.ai/help/en/articles/13975978-optimize-fin-instantly-with-the-help-of-ai), [Decagon](https://decagon.ai/product/suggestions)). Langfuse uses **annotation queues** so people label a sample and the judge is calibrated against them ([Langfuse](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues)). Hamming alerts **relative to baseline**, on sustained conditions, with cooldowns and a weekly false-positive review ([Hamming](https://hamming.ai/blog/monitor-voice-agents-in-production)). None of the sources describes checking a fix after it ships; that is where this CP goes further.

# What changes

1. **Learning actions.** At the end of each learning run (nightly or **Run learning now**), each agent's findings are turned into actions of five kinds, ranked by severity and impact, each with one next step:

   | Kind | Raised when | Next step | Closes itself when |
   |---|---|---|---|
   | `fix_not_holding` (high) | a `fixed` cluster gets ≥ 2 signals from calls after its fix was approved, within 14 days | the cluster is reopened (so the same run may draft again); roll back or review the new draft | the cluster is fixed again or ignored |
   | `answer_needed` (high) | a ready `missing_knowledge` cluster has no specialist note and no reviewer answer, so no draft is made | type the answer; it drafts and evaluates a fix | a note or answer exists, or the cluster has a proposal |
   | `check_failing` (high for a hard gate, else medium) | over the last 7 days of the published version, a check has ≥ 10 decided verdicts and fails on ≥ 20 % | for an uncalibrated judge check: review the 10 listed calls (labels calibrate the judge); otherwise open the failing calls | the fail rate drops below 20 %, or every listed call of an uncalibrated judge check has a review |
   | `drift` (high) | the published version drifts on goal met, grounded or containment (SC-10) | open Evaluation for the version | the drift flag clears |
   | `scenario_failing` (medium) | in the latest finished test run of the published version an enabled scenario passed fewer than all repeats (*flaky* when some passed) | open the test run | a later run of that version passes it, or the scenario is disabled, or a new version is published |

   **Done** and **Dismiss** (a note is optional) close an action by hand and keep the same finding from reopening for `learning.snooze_days`.
2. **Fixes are verified after they ship.** A cluster shows, once fixed, its signals per week in the 28 days before the fix and since: "Fix held: 1.5/week → 0/week" after 7 quiet days, or *Fix did not hold*.
3. **Knowledge comes from people.** The evidence the drafter sees carries only human answers: a specialist's resolution note or the reviewer's answer to `answer_needed`. A `missing_knowledge` cluster without either is not drafted (nightly or **Draft fix**, which returns 409 `answer_needed`); the cluster page asks for the answer.
4. **Where it shows.** Insights opens with **Needs attention** above the learning inbox; the dashboard's Self-learning card shows the count; the run report lists actions opened and closed.

# Affected specs

* [/architecture/learning-actions.md](/architecture/learning-actions.md) (new) - kinds, derivation, lifecycle, ranking; LA-01…LA-09
* [/architecture/self-learning.md](/architecture/self-learning.md) - nightly step 0 (verify fixes) and step 7 (actions); drafting needs a human answer for knowledge; report counts; SL-15, SL-16
* [/architecture/fleet-learning.md](/architecture/fleet-learning.md) - evidence carries human answers only; FL-09
* [/prompts/fix-draft.md](/prompts/fix-draft.md) - the evidence line says where the answer came from (no new variable)
* [/data/data-model.md](/data/data-model.md) - table `learning_actions`; `clusters.human_answer`, `human_answer_by`, `reopened_at`; DM-01 at 37 tables, DM-13
* [/api/rest-api.md](/api/rest-api.md) - `/api/insights/actions`, `/api/actions/{id}/done|dismiss|answer`; cluster `fix` and `needs_answer`; API-15
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) - job `draft_and_evaluate`, event `action.updated`
* [/ui/insights.md](/ui/insights.md) - Needs attention, answer form, fix held line; UI-67, UI-68
* [/ui/dashboard.md](/ui/dashboard.md) - count on the Self-learning card
* [/product/demo-walkthrough.md](/product/demo-walkthrough.md) - Act 6 shows Needs attention; a rerun reopens the fixed cluster instead of stalling
* [/product/roadmap.md](/product/roadmap.md) - R15, R18, R20 → CP-0032

# Acceptance criteria

Defined in the specs above: **LA-01…LA-09**, **SL-15**, **SL-16**, **FL-09**, **DM-13**, **API-15**, **UI-67**, **UI-68**.

# Tasks

1. Spec edits (this CP).
2. Model, schema upgrade, `voiceai/learning/actions.py` (derivation, lifecycle, fix verification) — LA-01…LA-09, DM-13.
3. Nightly: verify fixes first, derive actions last, report counts; drafting rule for knowledge — SL-15, SL-16, FL-09.
4. Routes and job `draft_and_evaluate` — API-15.
5. Web: Needs attention, answer form, fix line, dashboard count — UI-67, UI-68.
6. Tests in `tests/test_learning_actions.py`; demo runner and walkthrough.

# Risks and rollout

New table and three nullable columns, added by the schema upgrade. Existing clusters keep working; a seeded cluster with no human notes becomes `answer_needed` instead of being drafted from the AI summary. Actions are derived only by learning runs, so a demo shows them after **Run learning now**.

# Out of scope

A relevance-aware "no answer" signal (R17), per-agent readiness (R19), notifications outside the app (email, Slack), the gate changes of [CP-0033](/changes/cp-0033-proven-fixes-and-a-steadier-gate.md).
