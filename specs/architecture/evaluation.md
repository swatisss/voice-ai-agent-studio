---
type: Component Spec
title: Evaluation
description: Proving a fix before shipping it - simulated callers replay cluster cases and regression scenarios against baseline and candidate configs, graded by an LLM judge.
status: draft
tags: [architecture, evaluation, simulation]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Eval run (`run_eval` job)

An eval run is either a **proposal** run (`kind: proposal`, this page) or a **suite** run of the agent's test scenarios (`kind: suite`, [/architecture/test-suites.md](/architecture/test-suites.md)); both use the simulation loop below. A proposal run is created by `POST /api/proposals/{id}/evaluate`. Proposal → `evaluating`.

## Cases

* **Cluster cases** — up to `EV_MAX_CLUSTER_CASES` (default 6) member calls of the proposal's cluster, newest first, from the drafting evidence.
* **Held-out cases** — up to 4 other member calls of the cluster, not in the drafting evidence ([/architecture/self-learning.md](/architecture/self-learning.md), Gate).
* **Derived cases** — the proposal's derived scenarios. Each case: `caller_goal` (from analysis), caller profile (member ID + DOB if the original call was verified), `expected: resolved`.
* **Regression scenarios** — all enabled `eval_scenarios` for the agent, the same scenarios as its [test suite](/architecture/test-suites.md) ([/demo-data/evergreen-health.md](/demo-data/evergreen-health.md) seeds 8), each played once with its own persona and memory. Each has its own `expected` (`resolved` or `escalated`).

## Arms

* **baseline** — the agent's current published version config.
* **candidate** — baseline config with the proposal payload applied in memory (draft doc included in `knowledge_doc_ids`, draft skill/tool added, or rule appended). Nothing is persisted to the agent.

Every case runs on both arms. Regression scenarios run `learning.regression_repeats` times (default 3) on each arm, because a single stochastic run cannot show a regression; the other cases run once. Every simulated call gets a scorecard (judge on), as in [test suites](/architecture/test-suites.md).

## Simulation

For each (case, arm): a `simulation` call is created (`is_eval: true`, excluded from dashboard, clustering and [call scoring](/architecture/call-scoring.md)) and driven by:

1. `AgentSession.start()` (greeting).
2. Simulator ([/prompts/caller-simulator.md](/prompts/caller-simulator.md), role `simulator`) produces the caller's next line given goal, profile, caller style (`calm` for cluster cases; the scenario's persona, with its stand-in memory, for regression scenarios and suite runs) and transcript; it outputs `[HANGUP]` when done or stuck.
3. `AgentSession.respond()`.
4. Stop when the simulator hangs up, the agent ends or escalates (one extra caller line allowed after escalation is not needed — stop), or after 8 caller turns.

Concurrency: `EV_CONCURRENCY` (default 4) simulations at a time.

## Realtime agents

Simulated callers have no voice, so an agent on the realtime pipeline ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)) is simulated on the **text channel with the chat role `realtime`** (or the agent's `models.realtime`); no speech-model request is made. Prompt, tools, skills, knowledge and guards are shared and get exercised, the speech model's wording and turn-taking do not. The run summary carries `pipeline` and `fidelity: "text_approximation"` and the Insights page shows the label next to the result (RV-14).

## Judging

The judge ([/prompts/eval-judge.md](/prompts/eval-judge.md), role `judge`) receives goal, expected outcome and transcript (with tool calls) and the check list `(none)` — eval runs do not use per-check verdicts yet; test suites will ([ADR-0011](/decisions/adr-0011-evaluation-and-self-learning.md)) — and returns `{outcome: resolved|escalated|abandoned, goal_met: bool, grounded: bool, policy_violations: [..], notes}`.

A case **passes** when (for regression scenarios, the test-suite rule of [/architecture/test-suites.md](/architecture/test-suites.md) applies instead):
* `expected: resolved` → `outcome == resolved` and `goal_met` and `grounded` and no `policy_violations`;
* `expected: escalated` → `outcome == escalated` and no `policy_violations`.

## Summary

```json
{ "cluster_cases": 6, "baseline_pass": 0, "candidate_pass": 5, "held_out_cases": 3, "held_out_baseline_pass": 0,
  "held_out_candidate_pass": 2, "derived_kept": 2, "regression_cases": 8, "regression_repeats": 3,
  "regression": {"<scenario id>": {"name": "Claim paid", "baseline": 3, "candidate": 3}}, "regression_pass": 8,
  "hard_fails": {"baseline": 0, "candidate": 0}, "p95_ms": {"baseline": 1180, "candidate": 1210},
  "lift_pct": 83, "gate": {"passed": true, "reasons": []}, "duration_s": 212 }
```

`regression_pass` counts scenarios that did not regress; the gate rules are in [/architecture/self-learning.md](/architecture/self-learning.md).

Progress events `eval.progress` (`{done, total, last: {case, arm, passed}}`) stream on topic `insights`. On completion proposal → `ready`; on failure → back to `draft` with the error.

# Acceptance

- **EV-01** — Given a proposal, when evaluated, then baseline and candidate results exist for every cluster, held-out and derived case, and `regression_repeats` results per arm for every enabled test scenario, each with a scorecard.
- **EV-02** — Given an eval run, when it completes, then no agent config or version was changed and the draft doc is still `draft`.
- **EV-03** — Given simulation calls, then they are excluded from dashboard metrics and from clustering.
- **EV-04** — Given a simulator that never hangs up, when 8 caller turns are reached, then the simulation stops.
- **EV-05** — Given an `expected: escalated` scenario where the agent escalates with no policy violations, then the case passes.
- **EV-06** — Given an eval in progress, then `eval.progress` events are published after each case-arm completes.
