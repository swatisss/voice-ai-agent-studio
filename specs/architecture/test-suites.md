---
type: Component Spec
title: Test suites
description: Offline evaluation - per-agent scenarios with expectations, each run k times by a simulated caller against the published version, the draft or an earlier version, scored with the call scorer and reported as pass rate and pass^k.
status: draft
tags: [architecture, evaluation, simulation, testing]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-31T00:00:00Z" }
---

# Purpose

Before a change reaches callers, a builder can check how an agent behaves on the situations that matter to them. A **test suite** is the agent's set of **scenarios**; a **test run** plays every enabled scenario `k` times with the [caller simulator](/prompts/caller-simulator.md) against one agent config and scores each simulated call with the [call scorer](/architecture/call-scoring.md). It shares the simulation loop with [proposal evaluation](/architecture/evaluation.md) and is part of the plan in [ADR-0011](/decisions/adr-0011-evaluation-and-self-learning.md). In this change test runs only **report**; nothing is gated on them (gating comes with self-learning, CP-0022).

# Scenario

One `eval_scenarios` row per scenario ([/data/data-model.md](/data/data-model.md)), per agent:

| Field | Meaning |
|---|---|
| `name` | 1–120 chars, unique per agent |
| `caller_goal` | 10–600 chars, the simulator's goal |
| `caller_profile` | name, member ID, date of birth and extra facts the caller shares when asked; `{}` = not a member |
| `persona` | `calm` (default) · `confused` · `impatient` · `adversarial` (the simulator's style, below) |
| `expected` | `resolved` or `escalated` |
| `required_tools` | ≤ 10 of `{name, args: {key: value}}`: each must be called at least once with a successful result and, for every listed key, an argument equal to the value (strings compared case-insensitively, trimmed) |
| `forbidden_tools` | ≤ 10 tool names that must never return a successful result |
| `expected_results` | ≤ 10 of `{tool, field, equals}`: some successful result of `tool` has `field` (dot path) equal to `equals` |
| `memory` | ≤ 5 facts (≤ 200 chars each) the agent is given as remembered about the caller (below) |
| `enabled` | default `true`; disabled scenarios are kept but not run |

Names of `required_tools`, `forbidden_tools` and `expected_results` must be tools of the agent's draft or built-in tools (`search_knowledge`, `escalate_to_human`, `end_call`), else 422 `unknown_tool`. Scenario edits never change finished runs: each result keeps a copy of the scenario as it ran.

## Caller personas

The simulator prompt receives a `caller_style` line:

| Persona | Style given to the simulator |
|---|---|
| `calm` | Polite and clear; answers what is asked. |
| `confused` | Unsure of the right words, gives details in the wrong order and asks for things to be repeated once. |
| `impatient` | Short answers, interrupts with "can you just…", asks for a person if not helped after two tries. |
| `adversarial` | Tries to get member information before verifying, and the first time gives a date of birth with one digit wrong. |

## Scenario memory

Simulations never read or write member memory ([/architecture/agent-memory.md](/architecture/agent-memory.md)). A scenario's `memory` facts stand in for it: when the simulated caller is verified, the session puts them in the prompt's member memory block exactly as loaded facts would appear and records the "Memory loaded" event with `{memory_used: [], scenario_memory: <count>}`. Nothing is read from or written to `member_memories`, and no `extract_memory` job runs. The scorer then judges `memory.used_correctly` as for a real call.

# Test run

Started by `POST /api/agents/{id}/test-runs` ([/api/rest-api.md](/api/rest-api.md)) with a **target**:

| Target | Config simulated |
|---|---|
| `published` (default) | the published version's snapshot; 409 `not_published` without one |
| `draft` | the draft resolved like a publish would ([/data/agent-config.md](/data/agent-config.md), Version snapshot) without creating a version; a draft that would not publish → 422 with the same error |
| `version` | the snapshot of `version_id` (any version of the agent) |

The run (`eval_runs` with `kind: suite`) stores the target, the version it is based on (the target version, or the published version for a draft, or none), the resolved config, `repeats` (1–5, default 3), the trigger (`manual`, `builder`, `publish`) and the scenario ids. Only one suite run per agent may be `running`: another start → 409 `run_in_progress`. With no enabled scenario → 422 `no_scenarios`.

Job `run_test_suite` `{eval_run_id}`:

1. For each scenario and each repeat `1..k`, simulate as in [evaluation](/architecture/evaluation.md) (Simulation, 8 caller turns, the realtime text approximation), with the scenario's profile, persona and memory; `EV_CONCURRENCY` simulations at a time. Each simulated call is `channel: simulation`, `is_eval: true`, `agent_version_id` = the run's base version (or the published one for a draft).
2. Score the call with the call scorer using **the run's config** (not the stored version), with the judge always on (sampling does not apply), and the scenario's goal and `expected` given to the judge. The scorecard is stored like a real call's; simulation calls never appear in the Evaluation rollups ([/architecture/call-scoring.md](/architecture/call-scoring.md)).
3. Check the expectations in code from the call's events (below) and store one `eval_results` row per (scenario, repeat) with `passed`, the failures and the scenario copy.
4. Publish `test_run.progress` after each result; on completion store the summary and publish `test_run.finished` (topic `evaluation`, [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)). A crash marks the run `failed` with the error; finished results are kept.

## When one repeat passes

All of:

1. **Outcome** — escalated when the call has an escalation (or the judge's `outcome` is `escalated`), else the judge's `outcome`; it equals `expected`.
2. **Goal** — for `expected: resolved`, `outcome.goal_met` is `pass`.
3. **No hard fail** — the scorecard is not `hard_fail`.
4. **Tools** — every `required_tools` entry is met, no `forbidden_tools` entry returned a successful result, every `expected_results` entry is met.

Each failure is recorded as a short reason (`"Expected escalated, got resolved"`, `"get_claim_status was never called with claim_id=C-20931"`, `"Hard fail: Did the agent avoid: \"…\"?"`).

## Summary

```json
{ "scenarios": 6, "repeats": 3, "pass_all": 4, "pass_any": 5, "pass_rate": 0.83, "hard_fails": 0,
  "check_pass_rates": {"knowledge.grounded": 0.94}, "by_scenario": {"<id>": {"passed": 2, "of": 3}},
  "duration_s": 212, "pipeline": "cascade", "fidelity": "faithful" }
```

`pass_all` counts scenarios that passed every repeat (pass^k); `pass_any` scenarios that passed at least one (pass@k); `pass_rate` = passed repeats ÷ all repeats. `fidelity` is `text_approximation` for a realtime agent (RV-14).

# Triggers

* **Manual** — Evaluation → Test suites, choosing the target ([/ui/evaluation.md](/ui/evaluation.md)).
* **Builder** — **Run tests** in the agent builder runs the draft (saved first) ([/ui/agent-builder.md](/ui/agent-builder.md)); it never blocks Publish.
* **Publish** — when `evaluation.test_on_publish` is true (default), publishing from the builder or approving a fix proposal starts a run on the new version, so every version has a baseline. Versions created by the seeder start nothing.

# Acceptance

- **TEST-01** — Given a scenario with `required_tools` `[{name: "get_claim_status", args: {claim_id: "C-20931"}}]`, when a repeat calls `get_claim_status` only with `claim_id: "C-20977"`, then that repeat fails with a reason naming the tool and argument; when it is called with `c-20931 ` and succeeds, the requirement is met.
- **TEST-02** — Given a scenario with `forbidden_tools: ["submit_claim"]` and one with `expected_results: [{tool: "request_document", field: "status", equals: "queued"}]`, then a repeat in which `submit_claim` succeeded fails, and a repeat whose `request_document` result has `status: "queued"` meets the expected result.
- **TEST-03** — Given a suite of two scenarios run with `repeats: 3` where scenario A passes 3 of 3 and B 2 of 3, then the summary has `pass_all: 1`, `pass_any: 2`, `pass_rate` 0.83 and `by_scenario` 3/3 and 2/3, and six simulated calls exist, each with a judged scorecard.
- **TEST-04** — Given a draft that adds a `never` rule, when a run targets the draft, then its scorecards carry that rule's `never.<hash>` check, no agent version is created, and the draft is unchanged.
- **TEST-05** — Given a suite run already running for an agent, when another is started, then 409 `run_in_progress`; given an agent without a published version, a `published` target returns 409 `not_published`; given no enabled scenarios, 422 `no_scenarios`.
- **TEST-06** — Given a scenario with memory `["Prefers documents by email"]`, when the simulated caller is verified, then the agent's prompt contains that fact, a "Memory loaded" event with `scenario_memory: 1` is recorded, no `member_memories` or `memory_events` row is created and no `extract_memory` job is queued.
- **TEST-07** — Given `persona: adversarial`, then the simulator prompt carries the adversarial style line; given each persona, the style line is the one in the table.
- **TEST-08** — Given an agent with `evaluation.test_on_publish: true`, when the builder publishes, then one suite run starts on the new version with trigger `publish`; with `false`, or when the seeder publishes, none starts.
- **TEST-09** — Given a running suite, then `test_run.progress` is published after each result with `done` and `total`, and `test_run.finished` once with the summary; the run's simulated calls never appear in `GET /api/calls` or the Evaluation summary.
- **TEST-10** — Given a scenario edited after a run, then the run's results still show the scenario as it ran; a scenario naming a tool the agent does not have is rejected with 422 `unknown_tool`.
