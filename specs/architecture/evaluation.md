---
type: Component Spec
title: Evaluation
description: Proving a fix before shipping it - simulated callers replay cluster cases and regression scenarios against baseline and candidate configs, graded by an LLM judge.
status: stable
tags: [architecture, evaluation, simulation]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Eval run (`run_eval` job)

Created by `POST /api/proposals/{id}/evaluate`. Proposal → `evaluating`.

## Cases

* **Cluster cases** — up to `EV_MAX_CLUSTER_CASES` (default 6) member calls of the proposal's cluster, newest first. Each case: `caller_goal` (from analysis), caller profile (member ID + DOB if the original call was verified), `expected: resolved`.
* **Regression scenarios** — all `eval_scenarios` for the agent ([/demo-data/evergreen-health.md](/demo-data/evergreen-health.md) seeds 6). Each has its own `expected` (`resolved` or `escalated`).

## Arms

* **baseline** — the agent's current published version config.
* **candidate** — baseline config with the proposal payload applied in memory (draft doc included in `knowledge_doc_ids`, draft skill/tool added, or rule appended). Nothing is persisted to the agent.

Cluster cases run on both arms; regression scenarios run on the candidate only (they already pass on baseline by definition; their baseline result is not needed for the decision).

## Simulation

For each (case, arm): a `simulation` call is created (`is_eval: true`, excluded from dashboard and clustering) and driven by:

1. `AgentSession.start()` (greeting).
2. Simulator ([/prompts/caller-simulator.md](/prompts/caller-simulator.md), role `simulator`) produces the caller's next line given goal, profile and transcript; it outputs `[HANGUP]` when done or stuck.
3. `AgentSession.respond()`.
4. Stop when the simulator hangs up, the agent ends or escalates (one extra caller line allowed after escalation is not needed — stop), or after 8 caller turns.

Concurrency: `EV_CONCURRENCY` (default 4) simulations at a time.

## Judging

The judge ([/prompts/eval-judge.md](/prompts/eval-judge.md), role `judge`) receives goal, expected outcome and transcript (with tool calls) and returns `{outcome: resolved|escalated|abandoned, goal_met: bool, grounded: bool, policy_violations: [..], notes}`.

A case **passes** when:
* `expected: resolved` → `outcome == resolved` and `goal_met` and `grounded` and no `policy_violations`;
* `expected: escalated` → `outcome == escalated` and no `policy_violations`.

## Summary

```json
{ "cluster_cases": 6, "baseline_pass": 0, "candidate_pass": 5,
  "regression_cases": 6, "regression_pass": 6, "lift_pct": 83, "duration_s": 41 }
```

Progress events `eval.progress` (`{done, total, last: {case, arm, passed}}`) stream on topic `insights`. On completion proposal → `ready`; on failure → back to `draft` with the error.

# Acceptance

- **EV-01** — Given a proposal, when evaluated, then baseline and candidate results exist for every cluster case and candidate results for every regression scenario.
- **EV-02** — Given an eval run, when it completes, then no agent config or version was changed and the draft doc is still `draft`.
- **EV-03** — Given simulation calls, then they are excluded from dashboard metrics and from clustering.
- **EV-04** — Given a simulator that never hangs up, when 8 caller turns are reached, then the simulation stops.
- **EV-05** — Given an `expected: escalated` scenario where the agent escalates with no policy violations, then the case passes.
- **EV-06** — Given an eval in progress, then `eval.progress` events are published after each case-arm completes.
